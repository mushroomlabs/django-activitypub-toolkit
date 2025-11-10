from django.dispatch import Signal

notification_accepted = Signal(["notification"])
message_sent = Signal(["message"])
activity_processed = Signal(["activity"])
activity_done = Signal(["activity"])
