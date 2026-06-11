import json

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.core.exceptions import ObjectDoesNotExist


class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]

        if not self.user.is_authenticated:
            await self.close(code=4001)  # Unauthorized
            return

        # Ensure the group name is valid
        self.room_group_name = f"notifications_{self.user.id}"

        try:
            # Join room group
            await self.channel_layer.group_add(self.room_group_name, self.channel_name)
            await self.accept()
        except Exception as e:
            print(f"WebSocket connection error: {str(e)}")
            await self.close(code=4002)  # Connection error

    async def disconnect(self, close_code):
        if hasattr(self, "room_group_name"):
            try:
                await self.channel_layer.group_discard(
                    self.room_group_name, self.channel_name
                )
            except Exception as e:
                print(f"WebSocket disconnection error: {str(e)}")

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            message_type = data.get("type")

            if message_type == "mark_read":
                notification_id = data.get("notification_id")
                success = await self.mark_notification_read(notification_id)

                await self.send(
                    text_data=json.dumps(
                        {
                            "type": "notification_marked_read",
                            "success": success,
                            "notification_id": notification_id,
                        }
                    )
                )
        except json.JSONDecodeError:
            await self.send(
                text_data=json.dumps(
                    {"type": "error", "message": "Invalid JSON format"}
                )
            )
        except Exception as e:
            await self.send(text_data=json.dumps({"type": "error", "message": str(e)}))

    async def notification_message(self, event):
        try:
            await self.send(
                text_data=json.dumps(
                    {"type": "notification", "notification": event["notification"]}
                )
            )
        except Exception as e:
            print(f"Error sending notification: {str(e)}")

    @database_sync_to_async
    def mark_notification_read(self, notification_id):
        from subscriptions.models import Notification

        try:
            notification = Notification.objects.get(id=notification_id, user=self.user)
            notification.read = True
            notification.save()
            return True
        except ObjectDoesNotExist:
            return False
        except Exception as e:
            print(f"Error marking notification as read: {str(e)}")
            return False
