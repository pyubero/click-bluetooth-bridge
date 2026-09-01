# Autodiscovery should know which controller is which or ask
That is because as found in devices.json both controllers have the same serial number, except for the prefix: 0A for the DPAD and 0B for the ABXY.
If neither 0A nor 0B are found, then the script should ask the user which should be assigned to which.

{
  "F4:C4:59:03:A0:F3": {
    "firmware": "1.1.0",
    "first_seen": "2026-09-01T20:29:50",
    "hardware": "B.0",
    "last_seen": "2026-09-01T20:33:44",
    "manufacturer": "Zwift Inc",
    "name": "Zwift Click",
    "serial": "0B-34C45903A0F3"
  },
  "F4:C4:59:03:BC:6F": {
    "firmware": "1.1.0",
    "first_seen": "2026-09-01T20:29:43",
    "hardware": "B.0",
    "last_seen": "2026-09-01T20:34:06",
    "manufacturer": "Zwift Inc",
    "name": "Zwift Click",
    "serial": "0A-34C45903BC6F"
  }
}


# After autodiscovery succeeds, update config.toml
Update config.toml with the corresponding addresses so that next time it is launched it will know which controller is which. Most users will only have a pair of controllers at home, and always the same.

# Add the argument --autodiscover to force autodiscovery
When launching the main script

# Improve logging and export to a rotatory logfile.


