class EventBus:
    def __init__(self):
        self.subscribers = {}

    def subscribe(self, event_type, callback):
        if event_type not in self.subscribers:
            self.subscribers[event_type] = []
        self.subscribers[event_type].append(callback)

    def publish(self, event):
        event_type = event.get("type")
        if not event_type:
            print(f"[EventBus] Warning: Event missing 'type': {event}")
            return
            
        if event_type in self.subscribers:
            for callback in self.subscribers[event_type]:
                try:
                    callback(event)
                except Exception as e:
                    print(f"[EventBus] Error in callback for {event_type}: {e}")
