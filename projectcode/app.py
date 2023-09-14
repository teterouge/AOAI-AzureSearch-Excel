import os
from azure.identity import DefaultAzureCredential
from azure.identity import ClientSecretCredential
import openai
from azure.search.documents import SearchClient
from azure.search.documents.models import QueryType
from azure.storage.blob import BlobServiceClient
from flask import Flask, render_template, request, jsonify
from dotenv import load_dotenv
import logging
from logging.handlers import RotatingFileHandler


app = Flask(__name__)
# Initialise Logging
app.config["DEBUG"] = True
logging.basicConfig(level=logging.DEBUG)
handler = RotatingFileHandler('flask.log', maxBytes=10000, backupCount=1)
handler.setLevel(logging.DEBUG)
app.logger.addHandler(handler)

logger = logging.getLogger(__name__)

load_dotenv('.\Test_Build_V3\.env')
print(os.getcwd())

# Set the Environments
AZURE_STORAGE_ACCOUNT = os.environ.get("AZURE_STORAGE_ACCOUNT")
AZURE_STORAGE_CONTAINER = os.environ.get("AZURE_STORAGE_CONTAINER")
AZURE_OPENAI_GPT_Deployment = os.environ.get("AZURE_OPENAI_GPT_Deployment")
AZURE_SEARCH_SERVICE = os.environ.get("AZURE_SEARCH_SERVICE")
AZURE_SEARCH_INDEX = os.environ.get("AZURE_SEARCH_INDEX")
AZURE_OPENAI_SERVICE = os.environ.get("AZURE_OPENAI_SERVICE")
AZURE_OPENAI_CHATGPT_DEPLOYMENT = os.environ.get("AZURE_OPENAI_CHATGPT_DEPLOYMENT")
AZURE_OPENAI_CHATGPT_MODEL = os.environ.get("AZURE_OPENAI_CHATGPT_MODEL")
AZURE_OPENAI_EMB_DEPLOYMENT = os.environ.get("AZURE_OPENAI_EMB_DEPLOYMENT")
KB_FIELDS = [
    "Field1", "Field2", "Field3", #Truncating for Brevity
]

# Chat roles
SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"

system_message_chat_conversation = """
{Insert your own here - suggest looking at the Azure Demo}.
"""

chat_logs = [{"role" : SYSTEM, "content" : system_message_chat_conversation}]

summary_prompt_template = """
{Insert your own here - suggest looking at the Azure Demo}.

Search query:
"""
query_summary_conversations = [{"role": SYSTEM, "content": summary_prompt_template}]
user_input = "{Insert your own here - suggest looking at the Azure Demo}."

# Authenticate to Azure
try:
    azure_credential = DefaultAzureCredential(exclude_shared_token_cache_credential = True)
    app.logger.info("Azure credentials acquired")
except Exception as e:
    app.logger.error("Error acquiring Azure credentials: %s", str(e))
    raise e

# Configure OpenAI SDK
try:

    openai.api_base = f"https://{AZURE_OPENAI_SERVICE}.openai.azure.com/"
    openai.api_version = "2023-05-15"
    openai.api_type = "azure_ad"
    openai.api_key = azure_credential.get_token("https://cognitiveservices.azure.com/.default").token
    app.logger.info("OpenAI SDK configured")
except Exception as e:
    app.logger.error("Error configuring OpenAI SDK: %s", str(e))
    raise e

# Set up clients for Cognitive Search and Storage
try:
    search_client = SearchClient(
        endpoint=f"https://{AZURE_SEARCH_SERVICE}.search.windows.net",
        index_name=AZURE_SEARCH_INDEX,
        credential=azure_credential)
    app.logger.info("SearchClient Configured")

    blob_client = BlobServiceClient(
            account_url=f"https://{AZURE_STORAGE_ACCOUNT}.blob.core.windows.net",
            credential=azure_credential)
    blob_container_client = blob_client.get_container_client(AZURE_STORAGE_CONTAINER)
    app.logger.info("BlobServiceClient configured")
except Exception as e:
    app.logger.error("Error setting up the clients: %s", str(e))

@app.route('/test')
def test():
    return "Test Successful"

@app.route('/')
def index():
    logger.debug("Rendering index.html")
    return render_template("index.html")

@app.route('/chat', methods=['POST'])
def chat():
    app.logger.info("Chat endpoint hit!")
    try:
        logger.debug("Received POST request for /chat endpoint.")
        user_message = request.json['message']
        logger.debug(f"User message: {user_message}")
    
        # OpenAI convert user message to query
        query_summary_conversations.append({"role": USER, "content": user_message})

        # Exclude category, to simulate scenarios where there's a set of docs you can't see
        exclude_category = None

        logger.debug("About to call openai.ChatCompletion for query.")
        query_completion = openai.ChatCompletion.create(
            deployment_id=AZURE_OPENAI_CHATGPT_DEPLOYMENT,
            model=AZURE_OPENAI_CHATGPT_MODEL,
            messages=query_summary_conversations,
            temperature=0.7,
            max_tokens=2048,
            n=1)
        search = query_completion.choices[0].message.content
        logger.debug(f"Received search query from OpenAI: {search}")

        # Using OpenAI to compute query embedding
        query_vector = openai.Embedding.create(engine=AZURE_OPENAI_EMB_DEPLOYMENT, input=search)["data"][0]["embedding"]
        # Alternative if not using reranking with semantic search:
        # search_client.search(search, 
        #                      top=3, 
        #                      vector=query_vector if query_vector else None, 
        #                      top_k=50 if query_vector else None, 
        #                      vector_fields="embedding" if query_vector else None)

        # Query Azure Cognitive Search Index
        filter = "category ne '{}'".format(exclude_category.replace("'", "''")) if exclude_category else None
        r = search_client.search(search, 
                         filter=filter,
                         query_type=QueryType.SEMANTIC, 
                         query_language="en-us", 
                         query_speller="lexicon", 
                         semantic_configuration_name="default", 
                         top=3)
                         # vector=query_vector if query_vector else None, 
                         # top_k=50 if query_vector else None, 
                         # vector_fields="embedding" if query_vector else None)
        results = [str(doc['sheetName']) + " - " + str(doc['Field1']) + ": " + str(doc['Field2']) + ", " + str(doc['Field3'])  for doc in r] #Truncated

        content = "\n".join(results)

        user_content = user_message + " \nSOURCES:\n" + content

        chat_logs.append({"role": USER, "content": user_content })

        logger.debug("About to call openai.ChatCompletion for chat.")
        chat_completion = openai.ChatCompletion.create(
            deployment_id=AZURE_OPENAI_GPT_Deployment,
            model=AZURE_OPENAI_CHATGPT_MODEL,
            messages=chat_logs, 
            temperature=0.7, 
            max_tokens=2048, 
            n=1)
        chat_content = chat_completion.choices[0].message.content
        logger.debug(f"Received chat content from OpenAI: {chat_content}")
        '''
        reset user content to avoid sources in conversation history
        add source as a single shot in query conversation
        '''
        chat_logs[-1]["content"] = user_input
        chat_logs.append({"role":ASSISTANT, "content": chat_content})
        query_summary_conversations.append({"role":ASSISTANT, "content": chat_content})
    
        app.logger.info("Chat content: %s", chat_content)
        return jsonify({"message": chat_content})

    except Exception as e:
        app.logger.error("Error occurred: %s", str(e))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug=True)