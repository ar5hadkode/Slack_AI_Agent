from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from openai import OpenAI
from dotenv import load_dotenv
import urllib.parse
import os
import time
from flask import Flask
from RAG import get_or_create_retriever, ask_question_with_rag

load_dotenv()

slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

thread_context = {}

def cleanup_thread_contexts():
    """Clean up old thread contexts to prevent memory leaks"""
    global thread_context
    cutoff = time.time() - 24 * 60 * 60
    thread_context = {k: v for k, v in thread_context.items() if float(k) > cutoff}
    print(f"Cleaned up thread_context. Remaining threads: {len(thread_context)}")

def respond_in_thread(thread_ts, user_id, message, say):
    """Helper function to respond in a thread"""
    print(f"Responding in thread {thread_ts} to user {user_id}: {message}")
    say(text=f"<@{user_id}> {message}", thread_ts=thread_ts)

def get_clean_message(text, bot_user_id):
    """Remove bot mention from message"""
    if bot_user_id and f'<@{bot_user_id}>' in text:
        return text.replace(f'<@{bot_user_id}>', '').strip()
    return text.strip()

@slack_app.event("app_mention")
def handle_mention(event, say):
    user_id = event["user"]
    thread_ts = event.get("ts")
    channel_id = event["channel"]
    user_message = get_clean_message(event['text'], os.getenv("SLACK_BOT_USER_ID"))
    
    print(f"Received mention from {user_id} in thread {thread_ts}: {user_message}")
    
    if not user_message:
        respond_in_thread(thread_ts, user_id, "Please ask your question after mentioning me.", say)
        return

    thread_context[thread_ts] = {
        "status": "awaiting_intent",
        "user_id": user_id,
        "channel_id": channel_id,
        "last_message": user_message,
        "last_updated": time.time()
    }
    print(f"Stored context for thread {thread_ts}: {thread_context[thread_ts]}")

    say(
        text="Please select the type of question",
        blocks=[
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": "Hi! What type of question is this?"},
            },
            {
                "type": "actions",
                "elements": [
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Generic"},
                        "value": f"generic|{user_id}|{thread_ts}",
                        "action_id": "select_generic"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Company-specific"},
                        "value": f"company|{user_id}|{thread_ts}",
                        "action_id": "select_company"
                    },
                ]
            }
        ],
        thread_ts=thread_ts
    )

def handle_intent_response(intent_type, body, say):
    value = body["actions"][0]["value"]
    _, user_id, thread_ts = value.split("|")
    
    print(f"Intent selected: {intent_type} for thread {thread_ts} by user {user_id}")
    
    if thread_ts not in thread_context:
        say(text="Sorry, I lost context of this conversation. Please start over.", thread_ts=thread_ts)
        print(f"Context missing for thread {thread_ts}")
        return
    
    context = thread_context[thread_ts]
    user_message = context["last_message"]
    
    thread_context[thread_ts] = {
        "status": "active",
        "intent": intent_type,
        "user_id": user_id,
        "channel_id": context["channel_id"],
        "last_message": user_message,
        "last_updated": time.time()
    }
    print(f"Updated context for thread {thread_ts}: {thread_context[thread_ts]}")

    try:
        if intent_type == "generic":
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": user_message}
                ]
            )
            reply = response.choices[0].message.content
        else:
            retriever = get_or_create_retriever()
            reply = ask_question_with_rag(retriever, user_message)

        #respond_in_thread(thread_ts, user_id, reply, say)
        respond_in_thread(thread_ts, user_id, reply, say)

        instruction_msg = (
            f"_You are now in *{intent_type.capitalize()}* mode._\n"
            f"If you want to switch modes, use the following commands:\n"
            "`#switch generic` - for generic questions\n"
            "`#switch company` - for company-specific questions"
        )
        respond_in_thread(thread_ts, user_id, instruction_msg, say)
    except Exception as e:
        respond_in_thread(thread_ts, user_id, f"Error: {str(e)}", say)
        print(f"Error processing intent response for thread {thread_ts}: {str(e)}")

@slack_app.action("select_generic")
def handle_generic_button(ack, body, say):
    ack()
    print(f"Generic button clicked: {body['actions'][0]['value']}")
    handle_intent_response("generic", body, say)

@slack_app.action("select_company")
def handle_company_button(ack, body, say):
    ack()
    print(f"Company button clicked: {body['actions'][0]['value']}")
    handle_intent_response("company", body, say)

@slack_app.event("message")
def handle_message(event, say):
    if event.get("bot_id") or not event.get("user"):
        print("Skipping message: Bot message or no user")
        return

    thread_ts = event.get("thread_ts")
    user_id = event["user"]
    channel_id = event["channel"]
    text = get_clean_message(event.get("text", ""), os.getenv("SLACK_BOT_USER_ID"))

    print(f"Received message in thread {thread_ts} from user {user_id}: {text}")

    if len(thread_context) > 100:
        cleanup_thread_contexts()

    context = thread_context[thread_ts]
    print(f"Context for thread {thread_ts}: {context}")

    if user_id != context["user_id"]:
        respond_in_thread(thread_ts, user_id, "Only the original user can continue this thread.", say)
        print(f"User {user_id} not authorized for thread {thread_ts}")
        return

    if text.lower() == "#switch generic":
        thread_context[thread_ts]["intent"] = "generic"
        thread_context[thread_ts]["status"] = "active"
        thread_context[thread_ts]["last_updated"] = time.time()
        #respond_in_thread(thread_ts, user_id, "Switched to Generic mode.", say)
        respond_in_thread(thread_ts, user_id, (
        "Switched to *Generic* mode.\n"
        "If you want to switch again, use the following commands:\n"
        "`#switch company` - for company-specific questions"
    ), say)

        print(f"Switched to generic intent for thread {thread_ts}")
        return
    elif text.lower() == "#switch company":
        thread_context[thread_ts]["intent"] = "company"
        thread_context[thread_ts]["status"] = "active"
        thread_context[thread_ts]["last_updated"] = time.time()
        #respond_in_thread(thread_ts, user_id, "Switched to Company-specific mode.", say)
        respond_in_thread(thread_ts, user_id, (
        "Switched to *Company-specific* mode.\n"
        "If you want to switch again, use the following commands:\n"
        "`#switch generic` - for generic questions"
    ), say)

        print(f"Switched to company intent for thread {thread_ts}")
        return

    if context["status"] == "awaiting_intent":
        respond_in_thread(thread_ts, user_id, "Please select an intent for this thread using the buttons above.", say)
        print(f"Thread {thread_ts} awaiting intent")
        return

    intent = context.get("intent")
    if not intent:
        respond_in_thread(thread_ts, user_id, "No intent set for this thread. Please start over.", say)
        print(f"No intent set for thread {thread_ts}")
        return

    try:
        print(f"Processing message with intent {intent} for thread {thread_ts}")
        if intent == "generic":
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "You are a helpful assistant."},
                    {"role": "user", "content": text}
                ]
            )
            reply = response.choices[0].message.content
        else:
            retriever = get_or_create_retriever()
            reply = ask_question_with_rag(retriever, text)

        thread_context[thread_ts]["last_message"] = text
        thread_context[thread_ts]["last_updated"] = time.time()
        print(f"Updated context for thread {thread_ts}: {thread_context[thread_ts]}")

        respond_in_thread(thread_ts, user_id, reply, say)
    except Exception as e:
        respond_in_thread(thread_ts, user_id, f"Error: {str(e)}", say)
        print(f"Error processing message for thread {thread_ts}: {str(e)}")

flask_app = Flask(__name__)

@flask_app.route("/")
def home():
    return "Slack bot is running!"

if __name__ == "__main__":
    handler = SocketModeHandler(slack_app, os.getenv("SLACK_APP_TOKEN"))
    print("⚡️ Bolt app is running!")

    from threading import Thread
    flask_thread = Thread(target=lambda: flask_app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 10000))))
    flask_thread.start()

    handler.start()