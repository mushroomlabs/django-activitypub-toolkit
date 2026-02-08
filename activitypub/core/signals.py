from django.dispatch import Signal

notification_accepted = Signal(["notification"])
message_sent = Signal(["message"])
activity_processed = Signal(["activity"])
activity_done = Signal(["activity"])
document_loaded = Signal(["document"])
reference_field_changed = Signal()
reference_loaded = Signal(["reference", "graph"])
follow_request_accepted = Signal(["follow_request"])
follow_request_rejected = Signal(["follow_request"])
