(*
    KeepItGoing v2.0.1 — screen-detection-primary fix
*)

property minIdleDelay : 300
property maxIdleDelay : 600
property pollInterval : 30
property permissionDelay : 3
property maxSessionAge : 7200

property stateDir : "/tmp/claude-keepitgoing/"
property generatorScript : "__KIG_GENERATOR_PATH__"

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

-- cwd cache: lsof is the slowest call in the system (~1–3s per call).
-- Cache by tty path — ttys are stable for the life of a tab, so one lookup
-- per tab per script launch is plenty. User rarely cd's out of a project mid-session.
property cwdCacheTtys : {}
property cwdCacheVals : {}

-- Content-hash idle detection: instead of brittle spinner-char heuristics,
-- compare the last N non-blank lines of the visible screen against the prior
-- poll. If they're identical, nothing is being drawn → Claude is idle.
-- Tracks: session key → (last content, timestamp content last changed).
property screenCacheKeys : {}
property screenCacheContents : {}
property screenCacheChangeTimes : {}

-- Fetch-failure backoff: iTerm's `contents of session` can wedge permanently
-- on sessions with huge buffers (seen with 700k+ token Claude conversations).
-- After N consecutive failures we park the session for fetchBackoffSecs so
-- we stop hammering iTerm every tick. A single success clears the backoff.
property fetchFailKeys : {}
property fetchFailCounts : {}
property fetchFailUntilTs : {}
property fetchFailThreshold : 3
property fetchBackoffSecs : 300

-- Notification throttle (used sparingly — prefer auto-recovery over nagging).
property notifyLastKeys : {}
property notifyLastTimes : {}

-- Compaction detection: track sessions that just underwent context compaction.
-- When "Compacting conversation" appears on screen, the session key is added
-- here. The NEXT nudge is replaced with a "refresher" prompt that helps Claude
-- re-orient after losing context. The key is removed once the refresher fires.
property compactionPendingKeys : {}

on shellCmd(cmd)
	try
		return do shell script cmd
	on error
		return ""
	end try
end shellCmd

on logLine(msg)
	my shellCmd("echo \"[$(date '+%Y-%m-%d %H:%M:%S')] " & msg & "\" >> /tmp/claude-keepitgoing/app.log 2>/dev/null")
end logLine

on notifyUser(noteTitle, noteBody)
	-- Post a macOS Notification Center alert so the user sees things the
	-- script can't fix on its own (permission needed, session wedged, etc.).
	-- Always also log so there's a trail even if the banner is missed.
	my logLine("[KeepItGoing] NOTIFY | " & noteTitle & " | " & my sanitizeForLog(noteBody))
	try
		set safeTitle to my sanitizeForLog(noteTitle)
		set safeBody to my sanitizeForLog(noteBody)
		display notification safeBody with title "KeepItGoing" subtitle safeTitle sound name "Funk"
	end try
end notifyUser

on notifyUserOnce(notifyKey, noteTitle, noteBody)
	-- Rate-limit to one banner per notifyKey per 10 minutes so we don't
	-- spam the user with the same condition every poll.
	set now to my currentTimestamp()
	repeat with i from 1 to count of notifyLastKeys
		if item i of notifyLastKeys is notifyKey then
			if (now - (item i of notifyLastTimes)) < 600 then return
			set item i of notifyLastTimes to now
			my notifyUser(noteTitle, noteBody)
			return
		end if
	end repeat
	set end of notifyLastKeys to notifyKey
	set end of notifyLastTimes to now
	my notifyUser(noteTitle, noteBody)
end notifyUserOnce

on currentTimestamp()
	return (do shell script "date +%s") as number
end currentTimestamp

on userIdleSeconds()
	-- Returns how many seconds since the last keyboard/mouse input on this
	-- Mac, via macOS's IOHIDSystem. 0 means "using the machine right now";
	-- large numbers mean "away". Works on any Mac including M1/M2 — no
	-- presence-sensor hardware required. Returns -1 if the probe fails.
	try
		set raw to my shellCmd("ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print int($NF/1000000000); exit}'")
		if raw is "" then return -1
		return raw as number
	on error
		return -1
	end try
end userIdleSeconds

on isUserProbablyPresent()
	-- "Probably present" = input within the last 2 minutes. Generous on
	-- purpose: we don't want to flag the user as absent just because they
	-- looked away to think. Used to decide whether it's worth briefly
	-- notifying before a destructive/disruptive action, vs. just proceeding.
	set secs to my userIdleSeconds()
	if secs < 0 then return false
	return secs < 120
end isUserProbablyPresent

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
				end try
			end if
		end repeat
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
	try
		tell application "iTerm"
			set screenText to contents of theSession
		end tell
		
		set bottomText to my lastNonBlankLines(screenText, 15)
		
		-- INTELLIGENCE: Check if Claude is "thinking" (spinner/progress bars)
		-- If we see characters from the spinner list in the bottom lines, it's NOT idle.
		if my stringContainsAny(bottomText, claudeSpinnerChars) then
			return "working"
		end if
		
		-- Specific check for the permission menu
		if (bottomText contains "Do you want to proceed?") and (bottomText contains "1. Yes") then
			return "confirm"
		end if
		
		-- If we see the prompt character at the very start of the last line
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

on trimWhitespace(s)
	-- Strip leading and trailing spaces/tabs. Pure AppleScript, no shell.
	set n to count of characters of s
	if n is 0 then return ""
	set i to 1
	repeat while i ≤ n
		set ch to character i of s
		if ch is not " " and ch is not tab then exit repeat
		set i to i + 1
	end repeat
	set j to n
	repeat while j ≥ i
		set ch to character j of s
		if ch is not " " and ch is not tab then exit repeat
		set j to j - 1
	end repeat
	if j < i then return ""
	return text i thru j of s
end trimWhitespace

on collapseSpaces(s)
	-- Replace any run of 2+ spaces with a single space. Single pass, no regex.
	set out to ""
	set prevWasSpace to false
	repeat with c in characters of s
		set ch to contents of c
		if ch is " " or ch is tab then
			if not prevWasSpace then
				set out to out & " "
				set prevWasSpace to true
			end if
		else
			set out to out & ch
			set prevWasSpace to false
		end if
	end repeat
	return out
end collapseSpaces

on sanitizeForLog(s)
	-- Strip characters that would break the double-quoted shell echo in logLine:
	--   "  — closes the quoted string
	--   $  — triggers shell expansion
	--   `  — command substitution
	--   \  — escape chaos
	-- Also collapse any newlines to spaces so a multi-line snippet stays on one log line.
	set out to ""
	repeat with c in characters of s
		set ch to contents of c
		if ch is return or ch is linefeed or ch is tab then
			set out to out & " "
		else if ch is "\"" or ch is "$" or ch is "`" or ch is "\\" then
			set out to out & "?"
		else
			set out to out & ch
		end if
	end repeat
	return out
end sanitizeForLog

on getSessionSnippet(theSession)
	-- Returns a short, sanitized description of what's currently on screen:
	-- the last non-blank line, trimmed and capped at 120 chars. This is what
	-- makes the log actually useful — instead of "verdict=working" you get
	-- "verdict=working | last=✻ Cogitating… (12s · ↑ 1.2k tokens · esc to interrupt)"
	try
		tell application "iTerm"
			set screenText to contents of theSession
		end tell
		-- Grab last ~6 non-blank lines, then walk backwards finding the last
		-- one that has real content after trimming (TUI viewports pad lines
		-- with spaces, so isBlankLine isn't enough — a line can be "non-blank"
		-- by paragraph boundary but still all whitespace once stripped).
		set candidateBlock to my lastNonBlankLines(screenText, 6)
		set candidateLines to paragraphs of candidateBlock
		set lastLine to ""
		repeat with i from (count of candidateLines) to 1 by -1
			set trimmed to my trimWhitespace(item i of candidateLines)
			if trimmed is not "" then
				set lastLine to trimmed
				exit repeat
			end if
		end repeat
		-- Collapse runs of 2+ spaces into a single space before capping —
		-- otherwise terminal right-padding eats the 120-char budget and
		-- we end up truncating real content that lives further left.
		set lastLine to my collapseSpaces(lastLine)
		set lastLine to my trimWhitespace(lastLine)
		if (count of characters of lastLine) > 120 then
			set lastLine to (text 1 thru 120 of lastLine) & "…"
		end if
		return my sanitizeForLog(lastLine)
	on error
		return ""
	end try
end getSessionSnippet

on sendMenuAccept(theSession, menuKey)
	-- Two-stage menu accept that adapts to whatever key the menu expects:
	--   1. Write the key (e.g. "1", "y", "a") with NO newline so it lands
	--      as a pure keypress in Claude's menu handler.
	--   2. 150ms delay so Claude has time to process the keypress before
	--      the carriage return.
	--   3. Bare carriage return commits the selection.
	-- If menuKey is empty, we skip step 1 and just send the carriage return,
	-- which works for arrow-key menus where the cursor is already on the
	-- recommended option.
	try
		if menuKey is not "" then
			tell application "iTerm"
				with timeout of 5 seconds
					tell theSession
						write text menuKey newline no
					end tell
				end timeout
			end tell
			delay 0.15
		end if
		tell application "iTerm"
			with timeout of 5 seconds
				tell theSession
					write text "" newline yes
				end tell
			end timeout
		end tell
		return true
	on error errMsg
		my logLine("[KeepItGoing] menu accept error: " & my sanitizeForLog(errMsg))
		return false
	end try
end sendMenuAccept

on sendConfirmYes(theSession)
	-- Backwards-compatible shim used by the speculative blind-path code,
	-- which can't see the screen and so guesses "1" (the conventional
	-- recommended option, reinforced by the permanent directive in every
	-- generated prompt).
	return my sendMenuAccept(theSession, "1")
end sendConfirmYes

on extractMenuKey(tightBottom)
	-- Return the key character that accepts the recommended menu option.
	-- Priority chain:
	--   0. "Yes, and don't ask again" / similar — prefer stopping the prompt from repeating
	--   1. Explicit markers: "(recommended)", "(default)", "(safest)", "(best)", "(preferred)"
	--   2. Claude Code survey special case ("How is Claude doing...")
	--   3. Highlighted cursor ❯
	--   4. [Y/n] style patterns (capital is default)
	--   5. Middle option on 3+ option menus (Claude often recommends the middle)
	--   6. Empty (caller sends Return only)
	
	-- Pass 0: scan for "don't ask again" style options. Claude Code's
	-- permission menu often has "Yes" / "Yes, and don't ask again this
	-- session" / "No" — picking #2 stops the same permission prompt from
	-- firing repeatedly through the session. Prefer this over plain Yes.
	try
		set lineList0 to paragraphs of tightBottom
		repeat with ln0 in lineList0
			set lineContent0 to contents of ln0
			if lineContent0 contains "don't ask again" or lineContent0 contains "don't ask me again" or lineContent0 contains "don't show again" or lineContent0 contains "do not ask again" then
				repeat with c0 in characters of lineContent0
					set ch0 to contents of c0
					if ch0 ≥ "0" and ch0 ≤ "9" then return (ch0 as string)
					if ch0 ≥ "a" and ch0 ≤ "z" then return (ch0 as string)
					if ch0 ≥ "A" and ch0 ≤ "Z" then
						return (string id ((id of ch0) + 32))
					end if
				end repeat
			end if
		end repeat
	end try
	
	-- Pass 1: scan for any explicit "recommended"-family marker.
	try
		set lineList to paragraphs of tightBottom
		repeat with ln in lineList
			set lineContent to contents of ln
			if lineContent contains "recommended" or lineContent contains "Recommended" or lineContent contains "(default)" or lineContent contains "(Default)" or lineContent contains "(safest)" or lineContent contains "(best)" or lineContent contains "(preferred)" or lineContent contains "(suggested)" then
				repeat with c in characters of lineContent
					set ch to contents of c
					if ch ≥ "0" and ch ≤ "9" then return (ch as string)
					if ch ≥ "a" and ch ≤ "z" then return (ch as string)
					if ch ≥ "A" and ch ≤ "Z" then
						return (string id ((id of ch) + 32))
					end if
				end repeat
			end if
		end repeat
	end try
	
	-- Pass 2: Claude Code session survey — always pick "2" (Fine).
	if tightBottom contains "How is Claude doing" then return "2"
	
	-- Pass 3: highlighted cursor ❯.
	try
		set marker to "❯ "
		set pos to offset of marker in tightBottom
		if pos > 0 then
			set chPos to pos + 2
			if chPos ≤ (count of characters of tightBottom) then
				set ch to character chPos of tightBottom
				if ch ≥ "0" and ch ≤ "9" then return (ch as string)
				if ch ≥ "a" and ch ≤ "z" then return (ch as string)
				if ch ≥ "A" and ch ≤ "Z" then
					set asciiVal to (id of ch) + 32
					return (string id asciiVal)
				end if
			end if
		end if
	end try
	
	-- Pass 4: [Y/n] / (Y/n) — capital is default.
	if tightBottom contains "[Y/n]" then return "y"
	if tightBottom contains "(Y/n)" then return "y"
	if tightBottom contains "[y/N]" then return "n"
	if tightBottom contains "(y/N)" then return "n"
	if tightBottom contains "[N/y]" then return "n"
	if tightBottom contains "(N/y)" then return "n"
	if tightBottom contains "[n/Y]" then return "y"
	if tightBottom contains "(n/Y)" then return "y"
	
	-- Pass 5: Middle-option heuristic. Count how many numbered option
	-- lines exist (lines starting with "N. " or "N) " for N=1..9).
	-- Claude often places the recommended/balanced choice in the middle
	-- when no explicit marker is set. If 3+ options, pick the middle;
	-- if 2 options, still pick 1 (binary choices default to first).
	try
		set optionCount to 0
		set lineList2 to paragraphs of tightBottom
		repeat with ln2 in lineList2
			set lineContent2 to my trimWhitespace(contents of ln2)
			if (count of characters of lineContent2) ≥ 3 then
				set firstCh to character 1 of lineContent2
				set secondCh to character 2 of lineContent2
				if firstCh ≥ "1" and firstCh ≤ "9" and (secondCh is "." or secondCh is ")") then
					set optionCount to optionCount + 1
				end if
			end if
		end repeat
		if optionCount ≥ 3 then
			-- Middle option = ceil(count/2). For 3: pick 2. For 4: pick 2. For 5: pick 3.
			set midIdx to ((optionCount + 1) div 2)
			return (midIdx as string)
		else if optionCount = 2 then
			return "1"
		end if
	end try
	
	return ""
end extractMenuKey

on extractMenuQuestion(theText)
	-- Walk bottom-up for a "?" line, then grab 1-2 preceding non-blank,
	-- non-option lines as context. Returns them joined with " | " so the
	-- log stays single-line but captures what was actually being asked.
	set lineList to paragraphs of theText
	repeat with i from (count of lineList) to 1 by -1
		set ln to my trimWhitespace(item i of lineList)
		if ln is not "" and ln ends with "?" then
			set ctx to ln
			set grabbed to 0
			repeat with j from (i - 1) to 1 by -1
				if grabbed ≥ 2 then exit repeat
				set prev to my trimWhitespace(item j of lineList)
				if prev is not "" and prev does not contain "❯ " and prev does not contain "1. " and prev does not contain "2. " then
					set ctx to prev & " | " & ctx
					set grabbed to grabbed + 1
				end if
			end repeat
			return ctx
		end if
	end repeat
	return ""
end extractMenuQuestion

on extractSelectedOption(theText)
	set lineList to paragraphs of theText
	repeat with i from 1 to count of lineList
		set ln to my trimWhitespace(item i of lineList)
		if ln contains "❯ " then return ln
	end repeat
	return ""
end extractSelectedOption

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
	-- Two-stage write: text without newline, then a separate carriage return.
	-- iTerm's default `write text X` appends \n which Claude Code's TUI
	-- sometimes doesn't interpret as "submit". Splitting ensures the text
	-- lands in the input box first, then the explicit Return submits it.
	try
		tell application "iTerm"
			with timeout of 5 seconds
				tell theSession
					write text thePrompt newline no
				end tell
			end timeout
		end tell
		delay 0.15
		tell application "iTerm"
			with timeout of 5 seconds
				tell theSession
					write text "" newline yes
				end tell
			end timeout
		end tell
		return true
	on error errMsg
		my logLine("[KeepItGoing] send error: " & my sanitizeForLog(errMsg))
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

on cooldownForMode(modeName)
	-- Three send-cadence modes:
	--   "waiting" — Claude is idle awaiting input (recent Notification/Stop
	--               hook OR screen unchanged ≥ minIdleDelay). Nudge SOON because
	--               there's a real prompt waiting and we want quick value.
	--   "blind"   — couldn't read the screen (fetch wedged). We don't know
	--               state, so nudge SPARSELY to avoid spamming a session that
	--               might already be busy.
	--   "working" — default. Claude is mid-tool-call or screen still moving.
	--               Standard cadence so we keep it directed without piling on.
	if modeName is "waiting" then return my randomDelay(60, 180)
	if modeName is "blind" then return my randomDelay(300, 600)
	return my randomDelay(minIdleDelay, maxIdleDelay)
end cooldownForMode

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

on fetchBackoffRemaining(sessionKey, now)
	-- Returns seconds of remaining cooldown, or 0 if the session is not
	-- currently in backoff (either never failed or cooldown expired).
	repeat with i from 1 to count of fetchFailKeys
		if item i of fetchFailKeys is sessionKey then
			set untilTs to item i of fetchFailUntilTs
			if untilTs > now then return untilTs - now
			return 0
		end if
	end repeat
	return 0
end fetchBackoffRemaining

on recordFetchFail(sessionKey, now)
	-- Increment failure count. When it crosses fetchFailThreshold for the
	-- first time, arm the backoff AND return true so the caller can kick
	-- off auto-recovery (scrollback clear) and post a notification in the
	-- same iteration. Subsequent failures return false — cooldown is already
	-- in effect, nothing new to do.
	repeat with i from 1 to count of fetchFailKeys
		if item i of fetchFailKeys is sessionKey then
			set wasBelow to ((item i of fetchFailCounts) < fetchFailThreshold)
			set item i of fetchFailCounts to (item i of fetchFailCounts) + 1
			if (item i of fetchFailCounts) ≥ fetchFailThreshold then
				set item i of fetchFailUntilTs to now + fetchBackoffSecs
				if wasBelow then
					my logLine("[kig] fetch cooldown armed | key=" & sessionKey & " | for " & (fetchBackoffSecs as string) & "s after " & ((item i of fetchFailCounts) as string) & " consecutive failures")
					return true
				end if
			end if
			return false
		end if
	end repeat
	set end of fetchFailKeys to sessionKey
	set end of fetchFailCounts to 1
	set end of fetchFailUntilTs to 0
	return false
end recordFetchFail

on recordFetchSuccess(sessionKey)
	-- Clear any prior failure state for this session.
	repeat with i from 1 to count of fetchFailKeys
		if item i of fetchFailKeys is sessionKey then
			if (item i of fetchFailCounts) > 0 or (item i of fetchFailUntilTs) > 0 then
				my logLine("[kig] fetch recovered | key=" & sessionKey)
			end if
			set item i of fetchFailCounts to 0
			set item i of fetchFailUntilTs to 0
			return
		end if
	end repeat
end recordFetchSuccess


on getCachedCwd(theSession)
	-- Same job as getSessionCwd but cached by tty. First call for a new tty
	-- pays the lsof cost; every subsequent call is a list walk.
	set sessionTty to ""
	try
		tell application "iTerm"
			with timeout of 3 seconds
				set sessionTty to tty of theSession
			end timeout
		end tell
	end try
	if sessionTty is "" then return ""
	repeat with i from 1 to count of cwdCacheTtys
		if item i of cwdCacheTtys is sessionTty then
			return item i of cwdCacheVals
		end if
	end repeat
	set cwdResult to my shellCmd("lsof -a -d cwd -p $(lsof -t " & sessionTty & " 2>/dev/null | tail -1) -Fn 2>/dev/null | grep '^n' | tail -1 | sed 's/^n//'")
	if cwdResult is not "" then
		set end of cwdCacheTtys to sessionTty
		set end of cwdCacheVals to cwdResult
	end if
	return cwdResult
end getCachedCwd

on contentIdleDuration(sessionKey, newContent, now)
	-- Returns number of seconds the screen for this session has been
	-- unchanged. Returns 0 the first time we see a session (can't know yet)
	-- and any time the content differs from the prior observation.
	repeat with i from 1 to count of screenCacheKeys
		if item i of screenCacheKeys is sessionKey then
			if item i of screenCacheContents is newContent then
				return now - (item i of screenCacheChangeTimes)
			else
				set item i of screenCacheContents to newContent
				set item i of screenCacheChangeTimes to now
				return 0
			end if
		end if
	end repeat
	set end of screenCacheKeys to sessionKey
	set end of screenCacheContents to newContent
	set end of screenCacheChangeTimes to now
	return 0
end contentIdleDuration

on getSessionCwd(theSession)
	try
		tell application "iTerm"
			set sessionTty to tty of theSession
		end tell
		if sessionTty is not "" then
			set cwdResult to my shellCmd("lsof -a -d cwd -p $(lsof -t " & sessionTty & " 2>/dev/null | tail -1) -Fn 2>/dev/null | grep '^n' | tail -1 | sed 's/^n//'")
			if cwdResult is not "" then return cwdResult
		end if
	end try
	return ""
end getSessionCwd

on idle
	-- Capture wall-clock start so we can log iteration duration. If any single
	-- iteration starts taking longer than pollInterval, we're falling behind
	-- and the log will show it plainly instead of silently slipping cadence.
	set iterStart to my currentTimestamp()
	try
		-- Self-rotate the log if it grows past ~50KB.
		my shellCmd("cd /tmp/claude-keepitgoing && { [ -f app.log ] && [ $(wc -c < app.log) -gt 512000 ] && mv app.log app.$(date +%Y-%m-%d-%H%M%S).log; find . -name 'app.*.log' -mtime +3 -delete; } 2>/dev/null; true")
		set stateRecords to my readStateFiles()
		set now to iterStart

		-- ── GLOBAL CONTROL LOCKFILES (managed by `kig` CLI) ─────────────
		-- pause.lock        → skip all firing until removed
		-- snooze-until.txt  → skip until the contained epoch time
		-- fire-now.lock     → override cooldown once, then auto-clear
		-- cancel-next.lock  → skip ONE upcoming fire, then auto-clear
		set kigPaused to false
		try
			set kigPaused to (my shellCmd("test -f /tmp/claude-keepitgoing/pause.lock && echo yes || echo no")) is "yes"
		end try
		if kigPaused then
			my logLine("[kig] paused (pause.lock) — skipping poll")
			return pollInterval
		end if
		set kigSnoozed to false
		try
			set snoozeContent to my shellCmd("cat /tmp/claude-keepitgoing/snooze-until.txt 2>/dev/null || echo 0")
			set snoozeUntil to snoozeContent as integer
			set nowEpoch to (my shellCmd("date +%s")) as integer
			if snoozeUntil > nowEpoch then
				set kigSnoozed to true
				my logLine("[kig] snoozed " & ((snoozeUntil - nowEpoch) as string) & "s remaining")
			else if snoozeUntil > 0 then
				my shellCmd("rm -f /tmp/claude-keepitgoing/snooze-until.txt")
			end if
		end try
		if kigSnoozed then return pollInterval
		set kigFireNow to false
		try
			set kigFireNow to (my shellCmd("test -f /tmp/claude-keepitgoing/fire-now.lock && echo yes || echo no")) is "yes"
		end try

		-- Collect session references in one pass inside a bounded iTerm tell,
		-- then release the iTerm event queue before doing any per-session work.
		-- This minimizes the time iTerm spends blocked on Apple Events, which
		-- is the root cause of the "iTerm freezes 60–90s" complaint.
		set sessionRefs to {}
		set sessionNames to {}
		set sessionPriorities to {}
		try
			tell application "iTerm"
				with timeout of 5 seconds
					if (count of windows) is 0 then return pollInterval
					set wIdx to 0
					repeat with w in windows
						set wIdx to wIdx + 1
						set tIdx to 0
						repeat with t in tabs of w
							set tIdx to tIdx + 1
							repeat with s in sessions of t
								set end of sessionRefs to s
								set end of sessionNames to (name of s)
								-- Priority = window*1000 + tab. The tab that responds
								-- to Cmd+1 is always window 1 tab 1 → priority 1001,
								-- the lowest possible. Lower number = higher priority.
								set end of sessionPriorities to (wIdx * 1000 + tIdx)
							end repeat
						end repeat
					end repeat
				end timeout
			end tell
		on error errMsg
			my logLine("[KeepItGoing] iterm enumeration error: " & my sanitizeForLog(errMsg))
			return pollInterval
		end try
		
		-- TARGET SELECTION: nudges always land in the Claude Code tab that
		-- responds to Cmd+1 — meaning window 1, tab 1. We compute priority as
		-- (windowIndex * 1000 + tabIndex) during enumeration, then pick the
		-- lowest-priority session that's also a Claude tab. This matches what
		-- iTerm's ⌘N keyboard shortcut labels show in the tab bar.
		set targetIdx to 0
		set targetPri to 99999999
		repeat with idx from 1 to count of sessionRefs
			set candName to item idx of sessionNames
			if my isClaudeTab(candName) then
				set candPri to item idx of sessionPriorities
				if candPri < targetPri then
					set targetPri to candPri
					set targetIdx to idx
				end if
			end if
		end repeat
		if targetIdx = 0 then
			my logLine("[kig] no Claude tab found this tick")
			return pollInterval
		end if
		set targetWin to targetPri div 1000
		set targetTab to targetPri mod 1000
		my logLine("[kig] target: win=" & (targetWin as string) & " tab=" & (targetTab as string) & " (⌘" & (targetTab as string) & ") name=" & my sanitizeForLog(item targetIdx of sessionNames))
		
		repeat with idx from targetIdx to targetIdx
			set s to item idx of sessionRefs
			set sessionName to item idx of sessionNames
			if my isClaudeTab(sessionName) then
				if my getKigState(s) is "off" then
					-- opted out, skip silently
				else
					-- Cached cwd lookup (fast after the first hit per tab).
					set sessionCwd to ""
					try
						set sessionCwd to my getCachedCwd(s)
					end try
					
					-- Pre-compute the session key now so we can consult the fetch
					-- backoff table before attempting an expensive contents fetch on
					-- a session we already know is wedged.
					set sessionKey to sessionCwd
					if sessionKey is "" then set sessionKey to sessionName
					
					set cooldownLeft to my fetchBackoffRemaining(sessionKey, now)
					set fetchOk to false
					set screenText to ""
					if cooldownLeft > 0 then
						-- In cooldown — log once per poll and skip. No iTerm calls,
						-- no shell calls, no hash updates. Keeps iteration fast and
						-- iTerm's Apple Event queue unclogged.
						my logLine("[kig] fetch skipped (cooldown) | cwd=" & sessionCwd & " | remaining=" & (cooldownLeft as string) & "s")
					else
						try
							tell application "iTerm"
								with timeout of 10 seconds
									set screenText to contents of s
								end timeout
							end tell
							set fetchOk to true
							my recordFetchSuccess(sessionKey)
						on error errMsg
							my logLine("[KeepItGoing] contents fetch error | cwd=" & sessionCwd & " | err=" & my sanitizeForLog(errMsg))
							set justArmed to my recordFetchFail(sessionKey, now)
							if justArmed then
								-- Wedged session: we can't read its screen, but we'll
								-- still blind-send rate-limited nudges (handled below,
								-- outside the fetchOk guard). Tell the user about the
								-- wedge but don't ask them to do anything — automation
								-- continues. User can ⌘K the tab when convenient.
								set presenceNote to ""
								if my isUserProbablyPresent() then
									set presenceNote to " — ⌘K the tab when you get a sec"
								else
									set presenceNote to ""
								end if
								my notifyUserOnce("wedged-" & sessionKey, "iTerm session wedged", "Scrollback buffer in " & sessionKey & " exceeded AppleScript bridge limits. Still sending nudges" & presenceNote & ".")
							end if
						end try
					end if
					if fetchOk then
						
						set bottomText to my lastNonBlankLines(screenText, 15)
						-- (sessionKey already computed above before the fetch.)
						
						-- Content-hash idle detection. If the bottomText is identical
						-- to the prior observation for this session, Claude is not
						-- drawing anything new → idle. The duration tells us for how long.
						set idleDur to my contentIdleDuration(sessionKey, bottomText, now)
						
						-- COMPACTION DETECTION. "Compacting conversation" appears in
						-- the terminal during/after context compaction. When spotted,
						-- flag this session so the NEXT nudge sends a refresher prompt
						-- that helps Claude re-orient instead of a regular directive.
						-- We don't send the refresher NOW (Claude is still processing
						-- the compaction); the flag is consumed on the next prompt cycle.
						if bottomText contains "Compacting conversation" then
							if sessionKey is not in compactionPendingKeys then
								set end of compactionPendingKeys to sessionKey
								my logLine("[kig] COMPACTION DETECTED | cwd=" & sessionCwd)
							end if
						end if
						
						-- Confirm-menu detection. Look only at the TIGHT bottom (last 5
						-- non-blank lines) — the 15-line window pulled stale menu text
						-- from scrollback and fired confirm on chats where the menu
						-- was long gone. Also require the distinctive "❯ 1. Yes" cursor
						-- line so help text and docs can't false-positive.
						set tightBottom to my lastNonBlankLines(screenText, 5)
						-- Broad menu detection: any of the common shapes that have a single
						-- "first / top / recommended" answer we should pick automatically.
						--   Claude Code numbered menu:  `❯ 1.` on a line → pick "1"
						--   Claude Code lettered menu:  `❯ a.` on a line → pick "1" (menus accept numbers too)
						--   Generic [Y/n] prompts:       presence of `[Y/n]`, `(Y/n)`, `(y/N)`, etc.
						-- The tightBottom window is only the last 5 non-blank lines so stale
						-- scrollback menus can't false-positive.
						set isConfirm to false
						if (tightBottom contains "❯ 1.") or (tightBottom contains "❯ 2.") then set isConfirm to true
						if (tightBottom contains "[Y/n]") or (tightBottom contains "(Y/n)") then set isConfirm to true
						if (tightBottom contains "[y/N]") or (tightBottom contains "(y/N)") then set isConfirm to true
						-- Claude Code session rating survey: "How is Claude doing this session?"
						-- Always pick "2: Fine" to dismiss without stalling.
						if tightBottom contains "How is Claude doing" then set isConfirm to true
						
						-- Hook-recency guard: only PreToolUse/PostToolUse events mean
						-- Claude is actively mid-tool-call. CRITICAL: Notification,
						-- Stop, and SessionEnd must NOT be treated as "working" —
						-- Notification in particular fires *precisely* when Claude is
						-- idle waiting for user input, which is exactly when we want
						-- to nudge it.
						set hookWorking to false
						set hookEventName to ""
						set hookEventAge to -1
						if sessionCwd is not "" then
							set stateRecord to my findStateForCwd(stateRecords, sessionCwd)
							if stateRecord is not missing value then
								set stateAge to now - (eventTimestamp of stateRecord)
								set hookEventName to eventName of stateRecord
								set hookEventAge to stateAge
								if (hookEventName is "PreToolUse" or hookEventName is "PostToolUse") and stateAge < workingHookWindow and not (stateEnded of stateRecord) and stateAge < maxSessionAge then
									set hookWorking to true
								end if
							end if
						end if
						
						-- Compose verdict string for the log line.
						set verdictStr to "working"
						if isConfirm then
							set verdictStr to "confirm"
						else if hookWorking then
							set verdictStr to "hook-working(" & hookEventName & "," & (hookEventAge as string) & "s)"
						else if idleDur ≥ minIdleDelay then
							set verdictStr to "idle-" & (idleDur as string) & "s"
						else
							set verdictStr to "pending-" & (idleDur as string) & "s"
						end if
						
						set snippet to my collapseSpaces(my trimWhitespace(my lastNonBlankLines(screenText, 1)))
						if (count of characters of snippet) > 120 then set snippet to (text 1 thru 120 of snippet) & "…"
						set snippet to my sanitizeForLog(snippet)
						set safeTab to my sanitizeForLog(sessionName)
						my logLine("[kig] cwd=" & sessionCwd & " | tab=" & safeTab & " | verdict=" & verdictStr & " | last=" & snippet)
						
						-- ACTION: confirm menu → extract the recommended key and accept.
						if isConfirm then
							set timeSince to my getTimeSinceLastSend(sessionKey & "-confirm")
							if timeSince > 10 then
								set detectedKey to my extractMenuKey(tightBottom)
								set menuQuestion to my extractMenuQuestion(bottomText)
								set menuOption to my extractSelectedOption(bottomText)
								if my sendMenuAccept(s, detectedKey) then
									my recordSendTime(sessionKey & "-confirm")
									my logLine("[KeepItGoing] menu accept | cwd=" & sessionCwd & " | key=" & detectedKey & " | q=" & my sanitizeForLog(menuQuestion) & " | opt=" & my sanitizeForLog(menuOption))
								end if
							end if
							
							-- ACTION: nudge the session. No idle gating anymore — we send
							-- rate-limited prompts whether Claude is working or idle. Keeping
							-- it directed while it works is desired behavior.
						else
							-- Mode selection: detected-waiting (Notification/Stop hook
							-- recent OR screen stable past minIdleDelay) gets the short
							-- "waiting" cadence so nudges land quickly when there's a
							-- real prompt sitting there. Otherwise standard "working".
							set sendMode to "working"
							-- Compaction refresher: force waiting mode so the
							-- refresher prompt arrives quickly (60-120s) instead
							-- of the full working cooldown (300-600s). Claude just
							-- lost context — getting re-oriented fast matters.
							if sessionKey is in compactionPendingKeys then
								set sendMode to "waiting"
							end if
							-- Background shells: if Claude shows "shell still running"
							-- or "shells still running" it's waiting on a build/test,
							-- NOT idle for input. Force working mode so we don't
							-- pester it every 1-3 min while xcodebuild runs.
							set hasBackgroundShell to (bottomText contains "shell still running" or bottomText contains "shells still running")
							if hasBackgroundShell then
								set sendMode to "working"
							else if (hookEventName is "Notification") or (hookEventName is "Stop") or (hookEventName is "SessionEnd") then
								set sendMode to "waiting"
							else if (not hookWorking) and (idleDur ≥ minIdleDelay) then
								set sendMode to "waiting"
							end if
							set timeSince to my getTimeSinceLastSend(sessionKey)
							set requiredDelay to my cooldownForMode(sendMode)
							-- Fire-now lock from `kig fire` skips cooldown once.
							if kigFireNow then
								my shellCmd("rm -f /tmp/claude-keepitgoing/fire-now.lock")
								my logLine("[kig] fire-now — bypassing cooldown")
							end if
							if (not kigFireNow) and timeSince ≤ requiredDelay then
								set remainingCooldown to (requiredDelay - timeSince)
								if remainingCooldown < 0 then set remainingCooldown to 0
								try
									my shellCmd("printf '{\"mode\":\"" & sendMode & "\",\"cwd\":\"" & sessionCwd & "\",\"remaining\":" & (remainingCooldown as string) & ",\"required\":" & (requiredDelay as string) & ",\"written_at\":'$(date +%s)'}' > /tmp/claude-keepitgoing/next-fire.json")
								end try
								my logLine("[kig] bailout cooldown | mode=" & sendMode & " | cwd=" & sessionCwd & " | timeSince=" & (timeSince as string) & " | required=" & (requiredDelay as string))
							else
								-- When a background shell is running, send a light
								-- status check instead of a full directive prompt.
								-- Keeps the session alive without derailing the task.
								set thePrompt to ""
								-- COMPACTION REFRESHER: if this session recently
								-- compacted, replace the normal directive with a
								-- re-orientation prompt. Consumed once; the flag
								-- is cleared after sending.
								set isCompactionRefresh to false
								if sessionKey is in compactionPendingKeys then
									set isCompactionRefresh to true
									-- Remove sessionKey from pending list.
									set newPending to {}
									repeat with pk in compactionPendingKeys
										if (contents of pk) is not sessionKey then set end of newPending to (contents of pk)
									end repeat
									set compactionPendingKeys to newPending
									set thePrompt to "context compaction just completed — your memory of recent work may be degraded. before continuing: (1) run `git branch --show-current` and `git status` to orient yourself (2) re-read project CLAUDE.md for conventions (3) check ~/.claude/projects/ memory files for session context (4) review your task list if you have one. then resume what you were working on — do NOT start new work or switch context."
									my logLine("[kig] COMPACTION REFRESHER queued | cwd=" & sessionCwd)
								end if
								if not isCompactionRefresh and hasBackgroundShell then
									set statusChecks to {"status? anything to report while that runs?", "how's it going? any updates on the background task?", "still building? let me know if you're blocked on anything.", "quick check-in — anything you need from me while you wait?", "any progress to share? take your time, just checking in.", "background task still running? what's next once it finishes?", "just a nudge — if you're blocked on something, say so. otherwise carry on."}
									set thePrompt to item (random number from 1 to count of statusChecks) of statusChecks
								else if not isCompactionRefresh then
									set thePrompt to my generatePrompt(sessionCwd)
									-- Override from `kig edit`: if override-prompt.txt is non-empty, use it instead
									try
										set overridePath to "/tmp/claude-keepitgoing/override-prompt.txt"
										set overrideContent to my shellCmd("[ -s " & overridePath & " ] && cat " & overridePath & " || echo")
										if (count of characters of overrideContent) > 10 then
											set thePrompt to overrideContent
											my shellCmd("rm -f " & overridePath)
											my logLine("[kig] override prompt used (from kig edit) — cleared")
										end if
									end try
								end if
								if (count of characters of thePrompt) < 20 then
									my logLine("[kig] bailout short prompt | cwd=" & sessionCwd & " | len=" & ((count of characters of thePrompt) as string))
								else
									-- cancel-next lock from `kig cancel` skips ONE fire then auto-clears
									set kigCancelNext to false
									try
										set kigCancelNext to (my shellCmd("test -f /tmp/claude-keepitgoing/cancel-next.lock && echo yes || echo no")) is "yes"
									end try
									if kigCancelNext then
										my shellCmd("rm -f /tmp/claude-keepitgoing/cancel-next.lock")
										my logLine("[kig] cancel-next — skipping this fire (prompt=" & my sanitizeForLog(thePrompt) & ")")
									else
										-- PRE-FIRE CLASSIFIER: cheap LLM check of the target session state.
										-- If AI is asking the user a question, skip the fire and notify instead.
										set kigState to "unknown"
										set kigDirectQuestion to ""
										try
											set tailText to ""
											try
												tell application "iTerm"
													with timeout of 3 seconds
														set tailText to contents of s
													end timeout
												end tell
											end try
											set lastChunk to my lastNonBlankLines(tailText, 40)
											-- Write to tmp, invoke classifier, read state.
											set tmpFile to "/tmp/claude-keepitgoing/classify-input-" & sessionKey & ".txt"
											-- Sanitize sessionKey for filenames (replace / with _)
											set safeKey to my shellCmd("printf '%s' " & quoted form of sessionKey & " | tr '/' '_'")
											set tmpFile to "/tmp/claude-keepitgoing/classify-" & safeKey & ".txt"
											my shellCmd("cat > " & quoted form of tmpFile & " <<'KIGEOF'\n" & lastChunk & "\nKIGEOF")
											set classifyOut to my shellCmd("timeout 20 python3 ~/.claude/hooks/scripts/keepitgoing-classify.py --input-file " & quoted form of tmpFile & " --session " & quoted form of safeKey & " 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get(\"state\",\"unknown\") + \"|\" + (d.get(\"direct_question\") or \"\"))'")
											if classifyOut contains "|" then
												set AppleScript's text item delimiters to "|"
												set kigState to text item 1 of classifyOut
												set kigDirectQuestion to text item 2 of classifyOut
												set AppleScript's text item delimiters to ""
											end if
											my logLine("[kig] pre-fire classify | state=" & kigState & " | cwd=" & sessionCwd)
										end try
										-- Auto-escalation config flag (kig budget auto-escalate on/off)
										set kigAutoEscalate to false
										try
											set autoFlag to my shellCmd("python3 -c 'import json,pathlib;p=pathlib.Path.home()/\".claude/hooks/keepitgoing-config.json\";print(\"yes\" if p.exists() and json.loads(p.read_text()).get(\"auto_escalate\",False) else \"no\")' 2>/dev/null || echo no")
											set kigAutoEscalate to (autoFlag is "yes")
										end try
										if kigState is "asking_user" then
											my shellCmd("terminal-notifier -title 'KIG: AI asked you a question' -message " & quoted form of kigDirectQuestion & " -sound default 2>/dev/null || true")
											my logLine("[kig] SUPPRESS fire — AI is asking user: " & my sanitizeForLog(kigDirectQuestion))
										else if kigState is "blocked" and kigAutoEscalate then
											my logLine("[kig] AUTO-ESCALATE — state=blocked, invoking unstuck")
											my shellCmd("terminal-notifier -title 'KIG: auto-escalating stuck session' -message 'Sending to Opus for strategy nudge' 2>/dev/null || true")
											set unstuckOut to ""
											try
												set unstuckOut to my shellCmd("timeout 90 python3 ~/.claude/hooks/scripts/keepitgoing-unstuck.py --input-file " & quoted form of tmpFile & " 2>/dev/null || echo ''")
											end try
											if (count of characters of unstuckOut) > 20 then
												set thePrompt to unstuckOut
												my logLine("[kig] auto-escalation nudge obtained (" & (count of characters of unstuckOut as string) & " chars)")
											else
												my logLine("[kig] auto-escalation returned empty — falling back to normal prompt")
											end if
											if my sendPromptToSession(s, thePrompt) then
												my recordSendTime(sessionKey)
												my logLine("[KeepItGoing] prompt sent | mode=auto-escalate | cwd=" & sessionCwd & " | prompt=" & my sanitizeForLog(thePrompt))
											else
												my logLine("[kig] bailout send failed | cwd=" & sessionCwd)
											end if
										else
											if my sendPromptToSession(s, thePrompt) then
												my recordSendTime(sessionKey)
												my logLine("[KeepItGoing] prompt sent | mode=" & sendMode & " | cwd=" & sessionCwd & " | idleDur=" & (idleDur as string) & "s | prompt=" & my sanitizeForLog(thePrompt))
											else
												my logLine("[kig] bailout send failed | cwd=" & sessionCwd)
											end if
										end if
										end if
									end if
							end if
						end if
					end if -- end of if fetchOk
					
					-- BLIND NUDGE PATH: even if the screen fetch failed (wedged
					-- session), still send rate-limited prompts. We can't tell if
					-- a menu is showing, so any prompt text will land in Claude's
					-- input box. That's fine — the user's design is "keep it
					-- directed while it works", which means nudges are wanted
					-- regardless of state. Rate limit is the only gate.
					if not fetchOk and cooldownLeft = 0 then
						-- Blind path: we couldn't read the screen this tick. Send a
						-- rate-limited nudge anyway with the wider "blind" cadence so
						-- we don't carpet-bomb a session whose state we can't see.
						set timeSince to my getTimeSinceLastSend(sessionKey)
						set requiredDelay to my cooldownForMode("blind")
						if timeSince > requiredDelay then
							set thePrompt to my generatePrompt(sessionCwd)
							if (count of characters of thePrompt) ≥ 20 then
								-- SPECULATIVE MENU ACCEPT: when the user is away (HID
								-- idle past 120s), preface the blind nudge with a "1"
								-- so if Claude happens to be sitting on a numbered menu
								-- it picks the recommended option before our prompt
								-- lands. If there's no menu the "1" submits as a tiny
								-- harmless input. Skipped when the user is present so
								-- we never interrupt live typing.
								set didSpeculative to false
								if not (my isUserProbablyPresent()) then
									if my sendConfirmYes(s) then
										set didSpeculative to true
										my logLine("[kig] speculative menu accept | cwd=" & sessionCwd)
									end if
								end if
								if my sendPromptToSession(s, thePrompt) then
									my recordSendTime(sessionKey)
									set speculativeNote to ""
									if didSpeculative then set speculativeNote to " | spec-menu=yes"
									my logLine("[KeepItGoing] blind nudge sent | mode=blind | cwd=" & sessionCwd & speculativeNote & " | prompt=" & my sanitizeForLog(thePrompt))
								end if
							end if
						else
							my logLine("[kig] bailout cooldown | mode=blind | cwd=" & sessionCwd & " | timeSince=" & (timeSince as string) & " | required=" & (requiredDelay as string))
						end if
					end if
				end if
			end if
		end repeat
		
	on error errMsg
		try
			my logLine("[KeepItGoing] Error: " & my sanitizeForLog(errMsg))
		end try
	end try
	
	set iterDur to (my currentTimestamp()) - iterStart
	if iterDur > pollInterval then
		my logLine("[kig] slow iteration: " & (iterDur as string) & "s (pollInterval=" & (pollInterval as string) & ")")
	end if
	
	return pollInterval
end idle

on run
	set lastSentTimes to {}
	set lastSentNames to {}
	my shellCmd("mkdir -p " & stateDir)
	my logLine("[KeepItGoing v2.0.1] Started")
end run

on quit
	my logLine("[KeepItGoing v2.0.1] Stopped")
	-- Truncate log if it grows past ~50KB so it never fills up
	my shellCmd("cd /tmp/claude-keepitgoing && { [ -f app.log ] && [ $(wc -c < app.log) -gt 512000 ] && mv app.log app.$(date +%Y-%m-%d-%H%M%S).log; find . -name 'app.*.log' -mtime +3 -delete; } 2>/dev/null; true")
	continue quit
end quit






















