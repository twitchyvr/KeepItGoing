(*
    KeepItGoing v2.0.1 — screen-detection-primary fix
*)

property minIdleDelay : 60
property maxIdleDelay : 240
property pollInterval : 15
property permissionDelay : 3
property maxSessionAge : 7200

property stateDir : "/tmp/claude-keepitgoing/"
property generatorScript : "/Users/mattrogers/.claude/hooks/scripts/keepitgoing-generate.py"

property claudeSpinnerChars : {"⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏", "⠁", "⠂", "⠄", "⠐", "⠈", "⡀", "⢀", "⣀", "⣄", "⣤", "⣦", "⣶", "⣷", "⣿", "✳", "✻", "✶", "✷", "✸"}
property claudeNamePatterns : {"Claude Code", "claude", "python)"}

property permissionPatterns : {"Allow ", "[Y]es", "[N]o", "Yes [A]lways", "No A[l]ways", "(y)es / (n)o", "Allow?", "yes (a)lways"}
property idlePromptPatterns : {"❯", "claude>", "What would you like"}
-- How recently a hook event must have fired for us to consider Claude "working".
-- 120s is long enough to span typical long-running tool calls (builds, tests,
-- long greps, network ops) without false-flagging real idle.
property workingHookWindow : 120

property lastSentTimes : {}
property lastSentNames : {}

on shellCmd(cmd)
    try
        return do shell script cmd
    on error
        return ""
    end try
end shellCmd

on currentTimestamp()
    return (do shell script "date +%s") as number
end currentTimestamp

on stringContainsAny(theString, patternList)
    repeat with p in patternList
        if theString contains (contents of p) then
            return true
        end if
    end repeat
    return false
end stringContainsAny

on isClaudeTab(tabName)
    if my stringContainsAny(tabName, claudeNamePatterns) then return true
    if my stringContainsAny(tabName, claudeSpinnerChars) then return true
    return false
end isClaudeTab

on readStateFiles()
    set stateRecords to {}
    try
        set fileList to paragraphs of (my shellCmd("ls " & stateDir & "*.json 2>/dev/null"))
        repeat with filePath in fileList
            if (contents of filePath) is not "" then
                try
                    set jsonStr to my shellCmd("cat " & quoted form of (contents of filePath))
                    if jsonStr is not "" then
                        set parseCmd to "python3 -c \"import json,sys; d=json.load(sys.stdin); print(d.get('event','')); print(d.get('timestamp',0)); print(d.get('cwd','')); print(d.get('session_id','')); print(d.get('idle',False)); print(d.get('permission_pending',False)); print(d.get('ended',False)); print(d.get('project_name',''))\" <<< " & quoted form of jsonStr
                        set parsed to paragraphs of (my shellCmd(parseCmd))
                        if (count of parsed) ≥ 8 then
                            set stateRecord to {eventName:item 1 of parsed, eventTimestamp:(item 2 of parsed) as number, stateCwd:item 3 of parsed, stateSessionId:item 4 of parsed, stateIdle:(item 5 of parsed is "True"), statePermission:(item 6 of parsed is "True"), stateEnded:(item 7 of parsed is "True"), stateProject:item 8 of parsed}
                            set end of stateRecords to stateRecord
                        end if
                    end if
                on error
                end try
            end if
        end repeat
    on error
    end try
    return stateRecords
end readStateFiles

on findStateForCwd(stateRecords, targetCwd)
    set bestRecord to missing value
    set bestTime to 0
    repeat with rec in stateRecords
        if stateCwd of rec is targetCwd then
            if eventTimestamp of rec > bestTime then
                set bestRecord to contents of rec
                set bestTime to eventTimestamp of rec
            end if
        end if
    end repeat
    return bestRecord
end findStateForCwd

on detectSessionState(theSession)
    -- Returns: "confirm" | "idle" | "working" | "unknown"
    -- "confirm" = Claude Code is showing its menu-style permission prompt
    --   ("Do you want to proceed?" with "1. Yes" and "2. No"). Detection
    --   must be specific enough to never match stale scrollback.
    -- "idle" = empty input prompt with no active question.
    -- "working" = anything else (caller has already ruled out "working" via
    --   hook-event recency before falling back to this).
    try
        tell application "iTerm"
            set screenText to text of theSession
        end tell

        -- Strip trailing blank lines so "last N lines" actually means
        -- "the meaningful content at the bottom of the visible buffer",
        -- not "N lines of empty viewport padding."
        set bottomText to my lastNonBlankLines(screenText, 30)

        -- Confirmation prompt detection: matches Claude Code's permission
        -- dialog in all its variants (2-option Yes/No, 3-option Yes/Yes-with-edit/No,
        -- etc.) by requiring two markers:
        --   1. The literal question "Do you want to proceed?"
        --   2. The first option labeled "1. Yes"  (NOT "1. Delete" or other actions)
        -- This is safe because Claude Code's UI convention is that option 1 is
        -- always the plain "Yes" affirmative. We refuse to fire on hypothetical
        -- destructive prompts where option 1 might be something else.
        if (bottomText contains "Do you want to proceed?") ¬
            and (bottomText contains "1. Yes") then
            return "confirm"
        end if

        if my stringContainsAny(bottomText, idlePromptPatterns) then
            return "idle"
        end if
        return "working"
    on error
        return "unknown"
    end try
end detectSessionState

on isBlankLine(lineContent)
    -- Pure-AppleScript blank check: returns true iff the line has no
    -- non-whitespace characters. Avoids shell calls entirely.
    repeat with c in characters of lineContent
        set ch to contents of c
        if ch is not " " and ch is not tab then
            return false
        end if
    end repeat
    return true
end isBlankLine

on lastNonBlankLines(theText, n)
    -- Return the last `n` non-blank lines of the input as a single string.
    -- Critical for not getting fooled by trailing whitespace padding that
    -- TUI viewports leave below the actual content.
    set lineList to paragraphs of theText
    set kept to {}
    repeat with i from (count of lineList) to 1 by -1
        set lineContent to item i of lineList
        if not my isBlankLine(lineContent) then
            set beginning of kept to lineContent
            if (count of kept) ≥ n then exit repeat
        end if
    end repeat
    set out to ""
    repeat with l in kept
        set out to out & (contents of l) & linefeed
    end repeat
    return out
end lastNonBlankLines

on sendConfirmYes(theSession)
    -- Send "1" + Return as REAL key events via System Events.
    -- SAFETY GATES (any failure aborts the send):
    --   1. iTerm must be running.
    --   2. We must successfully select the target window/tab/session.
    --   3. After activate, iTerm2 MUST be the frontmost process. If not,
    --      something stole focus and we refuse to send — preventing the
    --      keystroke from leaking into Terminal.app, a code editor, or
    --      anything else that happens to be in front.
    --   4. We re-verify frontmost between the "1" keypress and the Return,
    --      so even if focus changes mid-send we abort the second key.
    try
        tell application "iTerm"
            if not running then return false
            activate
            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        if s is theSession then
                            select w
                            select t
                            select s
                        end if
                    end repeat
                end repeat
            end repeat
        end tell
        delay 0.35

        -- GATE: refuse to send unless iTerm2 is frontmost
        tell application "System Events"
            set frontProc to name of first application process whose frontmost is true
        end tell
        if frontProc is not "iTerm2" then
            my shellCmd("echo '[KeepItGoing] confirm aborted: front=" & frontProc & " (expected iTerm2)' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
            return false
        end if

        tell application "System Events"
            keystroke "1"
        end tell
        delay 0.1

        -- Re-verify frontmost before the Return
        tell application "System Events"
            set frontProc2 to name of first application process whose frontmost is true
        end tell
        if frontProc2 is not "iTerm2" then
            my shellCmd("echo '[KeepItGoing] confirm: focus lost between keys, front=" & frontProc2 & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
            return false
        end if

        tell application "System Events"
            key code 36 -- Return
        end tell
        return true
    on error errMsg
        my shellCmd("echo '[KeepItGoing] confirm error: " & errMsg & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
        return false
    end try
end sendConfirmYes

on generatePrompt(cwd)
    set cmd to "python3 " & quoted form of generatorScript
    if cwd is not "" then
        set cmd to cmd & " --cwd " & quoted form of cwd
    end if
    set prompt to my shellCmd(cmd)
    if prompt is "" then
        return "continue. keep going."
    end if
    return prompt
end generatePrompt

on sendPromptToSession(theSession, thePrompt)
    try
        tell application "iTerm"
            tell theSession
                write text thePrompt
            end tell
        end tell
        return true
    on error
        return false
    end try
end sendPromptToSession

-- sendPermissionApproval has been deleted. The user runs Claude in
-- bypass-permissions mode; Claude never asks for permission, so the entire
-- auto-approval path was pure liability (state-file false positives → "y" spam).
-- Removed entirely so no caller can ever exist.

on getTimeSinceLastSend(sessionName)
    set now to my currentTimestamp()
    repeat with i from 1 to count of lastSentNames
        if item i of lastSentNames is sessionName then
            return now - (item i of lastSentTimes)
        end if
    end repeat
    return 99999
end getTimeSinceLastSend

on recordSendTime(sessionName)
    set now to my currentTimestamp()
    set found to false
    repeat with i from 1 to count of lastSentNames
        if item i of lastSentNames is sessionName then
            set item i of lastSentTimes to now
            set found to true
            exit repeat
        end if
    end repeat
    if not found then
        set end of lastSentNames to sessionName
        set end of lastSentTimes to now
    end if
end recordSendTime

on randomDelay(lo, hi)
    set a to random number from lo to hi
    set b to random number from lo to hi
    return (a + b) div 2
end randomDelay

on getKigState(theSession)
    -- Returns "on" (default) or "off" based on the iTerm user variable
    -- "user.keepitgoing" set on this session. The user can toggle with the
    -- `kig` shell command. Errors and missing variables both return "on"
    -- so existing tabs without the var continue to be watched.
    set v to ""
    try
        tell application "iTerm"
            tell theSession
                set v to (variable named "user.keepitgoing")
            end tell
        end tell
    on error
        return "on"
    end try
    if v is "off" then return "off"
    return "on"
end getKigState

on getSessionCwd(theSession)
    try
        tell application "iTerm"
            set sessionTty to tty of theSession
        end tell
        if sessionTty is not "" then
            set cwdResult to my shellCmd("lsof -a -d cwd -p $(lsof -t " & sessionTty & " 2>/dev/null | tail -1) -Fn 2>/dev/null | grep '^n' | tail -1 | sed 's/^n//'")
            if cwdResult is not "" then return cwdResult
        end if
    on error
    end try
    return ""
end getSessionCwd

on idle
    try
        -- Self-rotate the log if it grows past ~50KB. Cheap: one wc + one mv only when needed.
        my shellCmd("if [ -f /tmp/claude-keepitgoing/app.log ] && [ $(wc -c < /tmp/claude-keepitgoing/app.log) -gt 51200 ]; then tail -200 /tmp/claude-keepitgoing/app.log > /tmp/claude-keepitgoing/app.log.tmp && mv /tmp/claude-keepitgoing/app.log.tmp /tmp/claude-keepitgoing/app.log; fi")
        set stateRecords to my readStateFiles()
        set now to my currentTimestamp()

        tell application "iTerm"
            if (count of windows) is 0 then return pollInterval

            repeat with w in windows
                repeat with t in tabs of w
                    repeat with s in sessions of t
                        set sessionName to name of s

                        if my isClaudeTab(sessionName) then
                            -- Per-session opt-out check: skip entirely if the user has
                            -- run `kig off` in this tab. Default is "on" so existing
                            -- tabs continue to be watched without action.
                            if my getKigState(s) is "off" then
                                -- skip this session
                            else
                            set sessionCwd to my getSessionCwd(s)
                            set sessionState to "unknown"
                            set stateRecord to missing value

                            if sessionCwd is not "" then
                                set stateRecord to my findStateForCwd(stateRecords, sessionCwd)
                            end if

                            -- ALWAYS run screen detection first. It's the only way to
                            -- catch confirmation prompts (which can appear while hook
                            -- events are still firing recently). The result tells us:
                            --   "confirm" — Claude Code is showing a permission menu prompt
                            --   "idle"    — empty input prompt, waiting for user
                            --   "working" — fallback if neither is detected
                            set screenVerdict to my detectSessionState(s)

                            -- Hook-event recency overrides screen "idle/working" but
                            -- NOT screen "confirm" — confirmations can be live while
                            -- hooks are still firing.
                            if screenVerdict is "confirm" then
                                set sessionState to "confirm"
                            else if stateRecord is not missing value then
                                set stateAge to now - (eventTimestamp of stateRecord)
                                if stateEnded of stateRecord then
                                    -- skip
                                else if stateAge > maxSessionAge then
                                    -- skip
                                else if stateAge < workingHookWindow then
                                    -- Recent hook event = Claude is working right now.
                                    set sessionState to "working"
                                else
                                    set sessionState to screenVerdict
                                end if
                            else
                                set sessionState to screenVerdict
                            end if

                            -- Dedup key: prefer cwd (stable across Claude title changes),
                            -- fall back to sessionName if cwd lookup failed.
                            set sessionKey to sessionCwd
                            if sessionKey is "" then set sessionKey to sessionName

                            if sessionState is "confirm" then
                                -- Auto-confirm "Do you want to proceed? 1. Yes" prompts
                                -- by pressing 1 + Return via System Events keystroke.
                                -- Cooldown 10s so we don't double-fire while the prompt
                                -- is being processed.
                                set timeSince to my getTimeSinceLastSend(sessionKey & "-confirm")
                                if timeSince > 10 then
                                    if my sendConfirmYes(s) then
                                        my recordSendTime(sessionKey & "-confirm")
                                        my shellCmd("echo '[KeepItGoing] confirm sent to " & sessionCwd & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
                                    end if
                                end if

                            else if sessionState is "idle" then
                                set timeSince to my getTimeSinceLastSend(sessionKey)
                                set requiredDelay to my randomDelay(minIdleDelay, maxIdleDelay)

                                if timeSince > requiredDelay then
                                    set thePrompt to my generatePrompt(sessionCwd)
                                    -- Length guard: never deliver anything shorter than
                                    -- 20 chars. The generator occasionally emits ultra-short
                                    -- variety like "yes." or "push." — symptomatically the
                                    -- same as the original "y" bug if delivered to Claude.
                                    if (count of characters of thePrompt) ≥ 20 then
                                        if my sendPromptToSession(s, thePrompt) then
                                            my recordSendTime(sessionKey)
                                        end if
                                    end if
                                end if
                            end if
                            end if -- end of getKigState opt-out check
                        end if
                    end repeat
                end repeat
            end repeat
        end tell

    on error errMsg
        try
            do shell script "echo '[KeepItGoing] Error: " & errMsg & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null"
        end try
    end try

    return pollInterval
end idle

on run
    set lastSentTimes to {}
    set lastSentNames to {}
    my shellCmd("mkdir -p " & stateDir)
    my shellCmd("echo '[KeepItGoing v2.0.1] Started at " & (current date) & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
end run

on quit
    my shellCmd("echo '[KeepItGoing v2.0.1] Stopped at " & (current date) & "' >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
    -- Truncate log if it grows past ~50KB so it never fills up
    my shellCmd("if [ -f /tmp/claude-keepitgoing/app.log ] && [ $(wc -c < /tmp/claude-keepitgoing/app.log) -gt 51200 ]; then tail -200 /tmp/claude-keepitgoing/app.log > /tmp/claude-keepitgoing/app.log.tmp && mv /tmp/claude-keepitgoing/app.log.tmp /tmp/claude-keepitgoing/app.log; fi")
    continue quit
end quit
