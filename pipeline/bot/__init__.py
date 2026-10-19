RELAY = "relay"
NEMO = "nemo"

APPS = (RELAY, NEMO)

NEEDS = {
    RELAY: ["RELAY_BOT_TOKEN"],
    NEMO: ["NEMO_BOT_TOKEN", "SLACK_TEAM_ID"],
}
