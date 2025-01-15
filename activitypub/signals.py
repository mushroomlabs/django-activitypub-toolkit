from django.dispatch import Signal

message_accepted = Signal(["message"])
message_sent = Signal(["message"])
activity_received = Signal(["activity"])
activity_processed = Signal(["activity"])
activity_done = Signal(["activity"])
