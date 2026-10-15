#!/bin/bash
# Helper for setting up bedroom-climate on macOS. Each step's output is also saved to
# mac/logs/<step>.log so it can be reviewed afterwards.
#   mac/step.sh env                 find Python >= 3.10, create .venv, install, run tests, smoke-test --demo
#   mac/step.sh app                 build mac/build/BedroomClimate.app (Bluetooth-capable launcher)
#   mac/step.sh scan                list nearby H5075 sensors with raw broadcast data
#   mac/step.sh scan-scale          list nearby Etekcity scales (step on the scale while it runs)
#   mac/step.sh watch NAME [MIN]    run in the foreground for MIN minutes (default 10) and log freshness
#   mac/step.sh agent-install NAME [plain|app] [ARGS...]   install the LaunchAgent (app = via
#                                   BedroomClimate.app); ARGS go to python, e.g. --scale ADDRESS --height-cm 175
#   mac/step.sh agent-status        is the background service running and storing data?
#   mac/step.sh agent-restart       launchctl kickstart -k, then check it recovers
#   mac/step.sh agent-uninstall     stop and remove the LaunchAgent
#   mac/step.sh info                LAN links, firewall and sleep settings (read-only)
set -u
cd "$(dirname "$0")/.." || exit 1
REPO="$PWD"
step="${1:-help}"; shift || true
mkdir -p mac/logs
exec > >(tee "mac/logs/$step.log") 2>&1
echo "== $step  $(date '+%F %T')  $(sw_vers -productName) $(sw_vers -productVersion) $(uname -m)"

find_python() {
  local c v best="" bestv=0
  for c in "$REPO/.venv/bin/python" /opt/homebrew/bin/python3.1[0-9] /opt/homebrew/bin/python3 \
           /usr/local/bin/python3.1[0-9] /usr/local/bin/python3 \
           /Library/Frameworks/Python.framework/Versions/3.1[0-9]/bin/python3 \
           "$HOME"/.pyenv/shims/python3 "$HOME"/.local/bin/python3* $(command -v -a python3 2>/dev/null) /usr/bin/python3; do
    [ -x "$c" ] || continue
    v=$("$c" -c 'import sys;print(sys.version_info[0]*100+sys.version_info[1])' 2>/dev/null) || continue
    echo "  candidate: $c -> $("$c" --version 2>&1)" >&2
    if [ "$v" -ge 310 ] && [ "$v" -gt "$bestv" ]; then best="$c"; bestv="$v"; fi
  done
  echo "$best"
}

LABEL=local.bedroom-climate
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
DATA_DIR="$HOME/Library/Application Support/bedroom-climate"
DB="$DATA_DIR/climate.db"
LOG="$HOME/Library/Logs/bedroom-climate.log"
APP="$REPO/mac/build/BedroomClimate.app"
DOMAIN="gui/$(id -u)"

build_app() {  # BedroomClimate.app: a launcher whose Info.plist carries the Bluetooth usage string
  xcode-select -p >/dev/null 2>&1 || { echo "RESULT: needs Xcode Command Line Tools (clang)"; return 1; }
  rm -rf "$APP"; mkdir -p "$APP/Contents/MacOS"
  cp mac/Info.plist "$APP/Contents/Info.plist"
  clang -O2 -Wall -o "$APP/Contents/MacOS/BedroomClimate" mac/launcher.c || return 1
  codesign --force --sign - "$APP" && codesign -dv "$APP" 2>&1 | grep -E "^Identifier|^Signature"
}
PY_CMD() {  # PY_CMD LOGFILE args...: run the venv python as BedroomClimate.app, output to LOGFILE.
  # Started with `open`, the app is its own "responsible process", so macOS checks *its*
  # Info.plist and Bluetooth permission instead of the terminal's. Run directly from a terminal
  # (Warp, iTerm2...) the terminal stays responsible and python is killed with SIGABRT.
  local out="$1"; shift
  [ -x "$APP/Contents/MacOS/BedroomClimate" ] || build_app || return 1
  : > "$out"
  open -W -n -g -a "$APP" --stdout "$out" --stderr "$out" \
       --env PYTHONPATH="$REPO" --env PYTHONUNBUFFERED=1 --args "$REPO/.venv/bin/python" "$@"
}

api_report() {  # how fresh the newest climate reading is, rows in the last hour, and the last weigh-in
  "$REPO/.venv/bin/python" - "$1" <<'PY' 2>&1 || echo "  (dashboard not answering)"
import json, sys, time, urllib.request
base = "http://localhost:%s" % sys.argv[1]
get = lambda path: json.load(urllib.request.urlopen(base + path, timeout=5))
l = get("/api/climate/latest")
pts = get("/api/climate/history?hours=1")["points"]
last = time.strftime("%H:%M:%S", time.localtime(pts[-1][0])) if pts else "-"
print(time.strftime("%H:%M:%S"), "| status", l.get("status"), "age", l.get("age_s"), "s |",
      l.get("temp_c"), "°C", l.get("humidity"), "% batt", l.get("battery"), "rssi", l.get("rssi"),
      "| history 1h:", len(pts), "points, newest", last)
if any(t["id"] == "weight" for t in get("/api/home")["tabs"]):
    w = get("/api/weight/latest")
    fat = (w.get("metrics") or {}).get("body_fat_percentage")
    print("  weight:", "no weigh-in yet" if w["status"] != "ok" else
          f'{w["weight_kg"]} kg, body fat {fat} %, at {time.strftime("%F %H:%M", time.localtime(w["ts"]))}')
PY
}

case "$step" in
env)
  echo "-- looking for Python >= 3.10"
  PY=$(find_python)
  if [ -z "$PY" ]; then echo "RESULT: no Python >= 3.10 found"; exit 1; fi
  echo "-- using $PY"
  if [ ! -x .venv/bin/python ]; then "$PY" -m venv .venv || exit 1; fi
  .venv/bin/python --version
  .venv/bin/pip install -q --upgrade pip
  .venv/bin/pip install -r requirements.txt || exit 1
  .venv/bin/pip list 2>/dev/null | grep -i -E "bleak|pyobjc-framework-CoreBluetooth"
  echo "-- unit tests"
  .venv/bin/python -m unittest 2>&1 | tail -4
  echo "-- demo smoke test"
  .venv/bin/python -m home_dashboard --demo --port 8000 & pid=$!
  sleep 4
  curl -s -o /dev/null -w "GET / -> %{http_code}\n" http://localhost:8000/
  curl -s http://localhost:8000/api/climate/latest; echo
  kill $pid; wait $pid 2>/dev/null
  echo "RESULT: env ok"
  ;;
app)
  echo "-- terminal: TERM_PROGRAM=${TERM_PROGRAM:-?} ${__CFBundleIdentifier:-}"
  echo "-- clang: $(xcode-select -p 2>&1)"
  build_app && echo "RESULT: built $APP"
  ;;
scan)
  echo "-- terminal: TERM_PROGRAM=${TERM_PROGRAM:-?} ${__CFBundleIdentifier:-}  launcher: $([ -x "$APP/Contents/MacOS/BedroomClimate" ] && echo app || echo none)"
  PY_CMD "$REPO/mac/logs/scan-app.log" -m home_dashboard --scan "$@"
  echo "-- open exit code $?"; cat mac/logs/scan-app.log
  echo "-- Bluetooth power: $(system_profiler SPBluetoothDataType 2>/dev/null | grep -m1 -i 'State:' | xargs)"
  ;;
scan-scale)
  echo "-- step on the scale now; listening for 30 s"
  PY_CMD "$REPO/mac/logs/scan-scale-app.log" -m home_dashboard --scan-scale --scan-seconds 30
  echo "-- open exit code $?"; cat mac/logs/scan-scale-app.log
  ;;
watch)
  dev="${1:?usage: mac/step.sh watch NAME [MINUTES]}"; mins="${2:-10}"
  launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 && { echo "background service is running; stop it first (agent-uninstall)"; exit 1; }
  mkdir -p "$DATA_DIR"
  PY_CMD "$REPO/mac/logs/watch-app.log" -m home_dashboard --device "$dev" --db "$DB" -v & pid=$!
  stop_app() { pkill -TERM -f "BedroomClimate.app/Contents/MacOS/BedroomClimate" ; }
  trap stop_app EXIT
  echo "-- dashboard: http://localhost:8000  (running $mins min, app log in mac/logs/watch-app.log)"
  end=$(( $(date +%s) + mins*60 ))
  sleep 20
  while [ "$(date +%s)" -lt "$end" ]; do api_report 8000; sleep 30; done
  stop_app; wait $pid 2>/dev/null
  echo "-- app log tail"; grep -v "GET /" mac/logs/watch-app.log | tail -40
  ;;
agent-install)
  dev="${1:?usage: mac/step.sh agent-install NAME [plain|app] [ARGS...]}"; mode="${2:-plain}"
  shift; [ $# -gt 0 ] && shift
  extra=""  # further python arguments, XML-escaped for the plist
  for a in "$@"; do a=${a//&/&amp;}; a=${a//</&lt;}; a=${a//>/&gt;}; extra="$extra<string>$a</string>"; done
  mkdir -p "$DATA_DIR" "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
  # bootout returns before the old job is gone; bootstrapping too early fails with "5: Input/output error".
  if launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null; then
    for _ in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do
      launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1 || break
      sleep 0.5
    done
  fi
  prog=""
  if [ "$mode" = app ]; then
    [ -x "$APP/Contents/MacOS/BedroomClimate" ] || build_app || exit 1
    prog="<string>$APP/Contents/MacOS/BedroomClimate</string>"
  fi
  cat > "$PLIST" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    $prog
    <string>$REPO/.venv/bin/python</string>
    <string>-m</string><string>home_dashboard</string>
    <string>--device</string><string>$dev</string>
    <string>--db</string><string>$DB</string>
    $extra
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict><key>PYTHONUNBUFFERED</key><string>1</string></dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>10</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
PL
  plutil -lint "$PLIST" || exit 1
  echo "=== agent start $(date '+%F %T') mode=$mode" >> "$LOG"
  launchctl bootstrap "$DOMAIN" "$PLIST" || { echo "-- retrying in 3 s"; sleep 3; launchctl bootstrap "$DOMAIN" "$PLIST"; } || exit 1
  echo "-- installed ($mode). If macOS asks about Bluetooth, click Allow. Checking in 90 s..."
  sleep 90
  "$0" agent-status
  ;;
agent-status)
  launchctl print "$DOMAIN/$LABEL" 2>&1 | grep -E "state =|pid =|last exit|runs =|program =" || echo "not loaded"
  pid=$(launchctl print "$DOMAIN/$LABEL" 2>/dev/null | awk '/^\tpid =/{print $3}')
  [ -n "$pid" ] && ps -o pid,etime,command -p "$pid" | cat
  api_report 8000
  echo "-- $LOG (tail)"; grep -v "GET /" "$LOG" | tail -25
  ;;
agent-restart)
  before=$(launchctl print "$DOMAIN/$LABEL" 2>/dev/null | awk '/^\tpid =/{print $3}')
  launchctl kickstart -k "$DOMAIN/$LABEL" || exit 1
  sleep 5
  after=$(launchctl print "$DOMAIN/$LABEL" 2>/dev/null | awk '/^\tpid =/{print $3}')
  echo "-- pid before=$before after=$after; waiting 80 s for a new sample"
  sleep 80
  "$0" agent-status
  ;;
agent-uninstall)
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null && echo "stopped"
  rm -f "$PLIST" && echo "removed $PLIST"
  ;;
info)
  name=$(scutil --get LocalHostName)
  echo "LocalHostName: $name  ->  http://$name.local:8000"
  for i in en0 en1; do ip=$(ipconfig getifaddr $i) && echo "$i: $ip  ->  http://$ip:8000"; done
  echo "-- firewall"; /usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate
  /usr/libexec/ApplicationFirewall/socketfilterfw --getblockall
  /usr/libexec/ApplicationFirewall/socketfilterfw --listapps 2>/dev/null | grep -i -A1 python
  echo "-- power (pmset -g)"; pmset -g | grep -E -i "^ (sleep|displaysleep|disksleep|powernap|womp|autorestart|standby)"
  pmset -g assertions | grep -i -E "PreventSystemSleep|PreventUserIdleSystemSleep" | head -5
  ;;
*)
  sed -n 2,14p "$0"
  ;;
esac
