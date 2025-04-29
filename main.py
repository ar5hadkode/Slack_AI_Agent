from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
from openai import OpenAI
import os
from dotenv import load_dotenv
import urllib.parse
from RAG import get_or_create_retriever , ask_question_with_rag

load_dotenv()

slack_app = App(token=os.getenv("SLACK_BOT_TOKEN"))
openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

@slack_app.event("app_mention")
def handle_mention(event, say):
    print("Bot was mentioned in a message")
    user_id = event["user"]
    thread_ts = event.get("ts")
    user_message = event['text'].strip()
    
    encoded_message = urllib.parse.quote(user_message)

    say(
        text="What type of question would you like to ask?",
        thread_ts=thread_ts,
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
                        "value": f"generic|{user_id}|{thread_ts}|{encoded_message}",
                        "action_id": "select_generic"
                    },
                    {
                        "type": "button",
                        "text": {"type": "plain_text", "text": "Company-specific"},
                        "value": f"company|{user_id}|{thread_ts}|{encoded_message}",
                        "action_id": "select_company"
                    },
                ]
            }
        ]
    )

@slack_app.action("select_generic")
def handle_generic_button(ack, body, say):
    ack()
    value = body["actions"][0]["value"]
    type_, user_id, thread_ts, encoded_message = value.split("|")
    user_message = urllib.parse.unquote(encoded_message)

    try:
        response = openai_client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are a helpful assistant. Keep your answers clear and concise."},
                {"role": "user", "content": user_message}
            ]
        )
        
        bot_reply = response.choices[0].message.content
        say(text=f"<@{user_id}> {bot_reply}", thread_ts=thread_ts)
    except Exception as e:
        print(f"Error in generic response: {e}")
        say(f"<@{user_id}> Sorry, something went wrong while answering your question.", thread_ts=thread_ts)

@slack_app.action("select_company")
def handle_company_button(ack, body, say):
    ack()
    value = body["actions"][0]["value"]
    type_, user_id, thread_ts, encoded_message = value.split("|")
    user_message = urllib.parse.unquote(encoded_message)

    try:
        
        retriever = get_or_create_retriever() 

        rag_answer = ask_question_with_rag(retriever, user_message)

        say(text=f"<@{user_id}> {rag_answer}", thread_ts=thread_ts)
    except Exception as e:
        print(f"Error in company-specific RAG: {e}")
        say(f"<@{user_id}> Sorry, something went wrong while answering your company-specific question.", thread_ts=thread_ts)

if __name__ == "__main__":
    print("⚡️ Slack AI agent is running!")
    handler = SocketModeHandler(slack_app, os.getenv("SLACK_APP_TOKEN"))
    handler.start()
