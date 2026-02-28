class VirtualMatterDevice:
    def __init__(self):
        # Initialize 8 endpoints to "off"
        self.state = {i: "off" for i in range(1, 9)}

    def turn_on(self, endpoint):
        if endpoint in self.state:
            self.state[endpoint] = "on"
            print(f"[Virtual] Relay {endpoint} -> ON")
            return True
        return False

    def turn_off(self, endpoint):
        if endpoint in self.state:
            self.state[endpoint] = "off"
            print(f"[Virtual] Relay {endpoint} -> OFF")
            return True
        return False

    def get_state(self):
        return self.state
