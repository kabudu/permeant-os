class RecordingRuntime:
    def __init__(self):
        self.registered = []

    def register_permeant_block(self, payload, request=None):
        self.registered.append(payload["hash"])
        return {"success": True}

    def verify_permeant_hashes(self, payload, request=None):
        missing = [hash_value for hash_value in payload["block_hashes"] if hash_value not in self.registered]
        if missing:
            return {"success": False, "missing_hashes": missing}
        return {"success": True}


class RegisterOnlyRuntime:
    def __init__(self):
        self.registered = []

    def register_permeant_block(self, payload, request=None):
        self.registered.append(payload["hash"])
        return True


_RECORDING = RecordingRuntime()
_REGISTER_ONLY = RegisterOnlyRuntime()


def get_recording_runtime(payload=None, request=None):
    return _RECORDING


def get_register_only_runtime(payload=None, request=None):
    return _REGISTER_ONLY
