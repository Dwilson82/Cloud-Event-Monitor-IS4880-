from google.cloud import pubsub_v1
import json

project_id = "project-e3a6924b-8583-4f8a-b9d"
subscription_id = "cloudevent-sub"

subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path(project_id, subscription_id)

def callback(message):
    print(f"Received message: {message.data.decode('utf-8')}")
    message.ack()

streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
print("Listening for messages...")

try:
    streaming_pull_future.result()
except KeyboardInterrupt:
  
