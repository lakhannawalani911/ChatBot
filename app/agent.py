from typing import Optional
from typing_extensions import Annotated, TypedDict 
from langgraph.graph import START, END, StateGraph
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langchain.chat_models import init_chat_model
# from langchain_google_vertexai.chat_models import ChatVertexAI
from langchain_google_genai import ChatGoogleGenerativeAI
from langsmith import traceable
from app.config import get_settings
from dotenv import load_dotenv
load_dotenv(r"C:\Users\lakha\Visual Studio project\chatbot\ChatBot\.env")
class AgentState(TypedDict):
    message:Annotated[list[BaseMessage], add_messages]
    error: Optional[str]
    retry_count:int
    model_used:str


class ProductionAgent:
    """Production agent with retry, fallback and langsmith tracing"""
    def __init__(self):
        settings = get_settings()
        self.primary_llm = ChatGoogleGenerativeAI(model=settings.primary_model,
                                           temperature=0,
                                           timeout=30,
                                           max_retries=0,
                                           api_key=settings.gemini_api_key
                                           )
        self.fallback_llm = ChatGoogleGenerativeAI(model=settings.gemini_model_name,
                                           temperature=0,
                                           timeout=30,
                                           max_retries=0,
                                           api_key=settings.gemini_api_key
                                           )
        self.max_retries= settings.max_retries
        self.graph = self.__buildgraph()

    def __buildgraph(self):
        """build langgraph with state machine"""
        def process_message(state:AgentState) -> dict:
            try:
                response = self.primary_llm.invoke(state['message'])
                return {
                    "message":[response],
                    "error":None,
                    "model_used":"primary"
                }
            except Exception as e:
                return {
                        "error":str(e),
                        "retry_count":state["retry_count"]+1,
                        "model_used":""
                    }
        
        def try_fallback(state:AgentState):
            try:
                response = self.fallback_llm.invoke(state['message'])
                return {
                    "message":[response],
                    "error":"None",
                    "model_used":"fallback gemini"
                }
            except Exception as e:
                return {
                        "error":str(e),
                        "retry_count":state["retry_count"]+1,
                        "model_used":""
                    }
        
        def handle_error(state:AgentState):
            return {
                "message":[
                    AIMessage(content=(
                        "I'm sorry, I'm having trouble processing your request right now. Please try again in sometime."
                    ))
                ]
            }

        def route_after_processing(state:AgentState):
            """decide what to do next after primary model attempt"""
            if state["error"] is None:
                return "done"
            elif state["retry_count"]<self.max_retries:
                return "fallback"
            else:
                return "error"

        def route_after_fallback(state:AgentState):
            """decide waht to do after fallback attempots"""
            if state["error"] is None:
                return "done"
                return "error"

        graph = StateGraph(AgentState)
        graph.add_node("process",process_message)
        graph.add_node("fallback",try_fallback)
        graph.add_node("error", handle_error)

        graph.add_edge(START, "process")
        graph.add_conditional_edges(
            "process", route_after_processing,
            {"done":END,"fallback":"fallback","error":"error"}
        )
        graph.add_conditional_edges(
            "fallback",
            route_after_fallback,
            {"done":END,"error":"error"}
            )
        graph.add_edge("error",END)
        return graph.compile()

    @traceable(name="production-api")
    def invoke(self, message:str)->dict:
        """invoke the agent with uiser message
            returns: {"message":str, "model_used":str,"error":str|None}
        """
        result = self.graph.invoke({
                "message":[HumanMessage(content=message)],
                "error":"None",
                "retry_count":0,
                "model_used":"primary"
            })
        return {
            "response":result["message"][-1].content,
            "model_used":result.get("model_used","unknown"),
            "error":result.get("error")
        }

if __name__ == "__main__":
    agent  = ProductionAgent()
    queries = ["whatg is langchain in 1 sentence?", "what is langgraph in 2 sentence","differece between RAG and Fine tuning in 2 sentence."]
    for query in queries:
        print(agent.invoke(query))