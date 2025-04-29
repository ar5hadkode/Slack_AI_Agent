import os
from langchain_community.document_loaders import PyPDFLoader
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.embeddings import OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from langchain_community.chat_models import ChatOpenAI
from langchain.chains import RetrievalQA

INDEX_DIR = "faiss_index"
PDF_PATH = "agilekode-portfolio.pdf"

def get_or_create_retriever():
    embeddings = OpenAIEmbeddings(openai_api_key=os.getenv("OPENAI_API_KEY"))
    
    if os.path.exists(INDEX_DIR):
        vectorstore = FAISS.load_local(INDEX_DIR, embeddings, allow_dangerous_deserialization=True)

    else:
        loader = PyPDFLoader(PDF_PATH)
        documents = loader.load()
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(documents)
        vectorstore = FAISS.from_documents(chunks, embeddings)
        vectorstore.save_local(INDEX_DIR)
    
    return vectorstore.as_retriever()

def ask_question_with_rag(retriever, query):
    qa = RetrievalQA.from_chain_type(
        llm=ChatOpenAI(openai_api_key=os.getenv("OPENAI_API_KEY")),
        chain_type="stuff",
        retriever=retriever
    )
    return qa.run(query)
