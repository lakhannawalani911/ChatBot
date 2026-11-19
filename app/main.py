import time
import os
import math
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from langsmith import traceable
from dotenv import load_dotenv
import uvicorn
from app.config import get_settings
from app.models import (
    ChatRequest,ChatResponse,HealthResponse, MetricsResponse, ErrorResponse
)
from app.security import SecurityPipeline
from app.cache import ResponseCache
from app.monitoring import get_logger, MetricsCollector, RequestTimer
from app.agent import ProductionAgent
from pathlib import Path
from os.path import join as path_join
load_dotenv(path_join(str(Path(__file__).resolve().parent.parent),".env"))


logger = get_logger()

@asynccontextmanager
async def lifespan(app:FastAPI):
    global security, cache,metrics, agent
    settings = get_settings()
    logger.info("starting api",extra={"extra_data":
                                      {"environment":settings.app_env,
                                       "primary_model":settings.primary_model,
                                       "tracing_enabled":settings.langchain_tracing_v2,}
                                      })
    security = SecurityPipeline()
    cache = ResponseCache()
    metrics = MetricsCollector()
    agent= ProductionAgent()
    logger.info("All componend initialized!!!")
    yield
    logger.info("Shutting down",extra={"extra_data":metrics.get_summary()})

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Production Chat Bot",
              description="Prodcution ready chatbot",
              version="1.0.0",
              lifespan=lifespan)
app.state.limiter=limiter

@app.exception_handler(RateLimitExceeded)
async def rate_limiter_handle(request:Request, exc:RateLimitExceeded):
    expire_time = getattr(exc.ratelimit, "reset_at", 0)
    current_time = request.scope.get("slowapi_start_time", 0) # internal slowapi timestamp
    
    # Fallback to a clean integer calculation for Retry-After
    retry_after = math.ceil(max(0, expire_time - current_time)) or 60

    # 2. Return a standardized 429 response
    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        content={
            "error": "Too Many Requests",
            "detail": f"You have exceeded your request limit. please try after {retry_after}",
            "limit": str(exc.detail)  # e.g., "5 per 1 minute"
        },
        headers={
            "Retry-After": str(retry_after)
        }
    )


@app.post("/chat",response_model=ChatResponse)
@limiter.limit(get_settings().rate_limit)
@traceable(name="chatbot_endpoint")
async def chat(request:Request, body:ChatRequest):
    """
    Main End point
    Flow:
    1:Security check (injection, PII)
    2:cache lookup
    3:agent invoke
    4:output validation
    5:cache store
    6:Return response
    """
    with RequestTimer() as timer:
        security_notes = []
        is_allowed, cleaned_text, notes = security.check_input(body.message)
        if not is_allowed:
            logger.warning("Request blocked by security", extra={"extra_data":
                                                                 {"reason":notes,
                                                                  "thread_id":body.thread_id}}
                                                                  )
            metrics.record_request(latency_ms=0, 
                                   error=True)
            
            raise HTTPException(status_code=400,
                                detail="Your message was blocked by our security filters")

        cache_response= cache.get(cleaned_text)
        if cache_response is not None:
            metrics.record_request(latency_ms=0, cache_hit=True,input_tokens=0, output_tokens=0)
            
            logger.info("cache hit", 
                        extra={"extra_dara":{"thread_id":body.thread_id}})
            
            return ChatResponse(response=cache_response,
                                thread_id=body.thread_id,
                                model_used="cahche",
                                chached=True,
                                processing_time_ms=0,
                                )
        try:
            result = await agent.invoke(cleaned_text)
        except Exception as e:
            logger.error(f'Agent invocation failed {e}', extra={"extra_data":
                                                                {"thread_id":body.thread_id,
                                                                 "error":str(e)}})
            metrics.record_request(latency_ms=0,
                                   error=True)
            
            raise HTTPException(status_code=500, 
                                detail="An Error occored while processing your request")
        response_text = result["response"][0]['text']
        model_used = result["model_used"]
        validated_response,output_warning = security.output_validator.validate(response_text)
        security_notes.extend(output_warning)
        cache.set(cleaned_text, validated_response)

    input_token = int(len(cleaned_text.split())) * 1.3
    output_token = int(len(validated_response.split())) * 1.3

    metrics.record_request(latency_ms=timer.elapsed_ms,
                        input_tokens=input_token,
                        output_tokens=output_token,
                        cache_hit=False,
                        )

    return ChatResponse(response=validated_response,
                        thread_id=body.thread_id,
                        model_used=model_used,
                        cached=False,
                        processing_time_ms=round(timer.elapsed_ms,2))

@app.get("/metrics", response_model=MetricsResponse)
async def get_metrics():
    summary = metrics.get_summary()
    print(f'{summary=}')
    return MetricsResponse(**summary)

@app.get("/cache/stats")
async def get_cache():
    return cache.stats

@app.get("/health",response_model=HealthResponse)
async def health():
    setting = get_settings()
    checks = {"agent":agent is not None,
              "security": security is not None,
              "cache":cache is not None}
    all_healthy = all(checks.values())
    return HealthResponse(
        status="healthy" if all_healthy else "degrade",
        environment= setting.app_env,
        checks= checks
    )
