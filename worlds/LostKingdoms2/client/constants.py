""" Collection of commonly used constants for Lost Kingdoms 2. """

CLIENT_VERSION = "V0.1.13"
CLIENT_NAME = "Lost Kingdoms 2 Client"

AP_LOGGER_NAME = "Client"
AP_WORLD_VERSION_NAME = "APWorldVersion"

# All the dolphin connection messages used in the client
CONNECTION_REFUSED_STATUS = "Detected a non-randomized ROM for LK2. Please close and load a different one. Retrying in 5 seconds..."
CONNECTION_LOST_STATUS = "Dolphin connection was lost. Please restart your emulator and make sure LK2 is running."
NO_SLOT_NAME_STATUS = "No slot name was detected. Ensure a randomized ROM is loaded. Retrying in 5 seconds..."
CONNECTION_VERIFY_SERVER = "Dolphin was confirmed to be opened and ready, Connect to the server when ready..."
CONNECTION_INITIAL_STATUS = "Dolphin emulator was not detected to be running. Retrying in 5 seconds..."
CONNECTION_CONNECTED_STATUS = "Dolphin is connected, AP is connected, Ready to play LK2!"
AP_REFUSED_STATUS = "AP Refused to connect for one or more reasons, see above for more details."

# Wait timer constants for between loops
WAIT_TIMER_SHORT_TIMEOUT: float = 0.125
WAIT_TIMER_MEDIUM_TIMEOUT: float = 1.5
WAIT_TIMER_LONG_TIMEOUT: float = 5
