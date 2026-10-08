import azure.functions as func
import logging
import sys
import os

# Add backend to path for imports: bundled copy when deployed, repo backend for local runs
function_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(function_dir, 'backend')
if not os.path.isdir(backend_path):
    backend_path = os.path.abspath(os.path.join(function_dir, '..', '..', 'backend'))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

app = func.FunctionApp()

PIPELINE_BUDGET_SECONDS = 8 * 60

def automation_enabled() -> bool:
    """The automated pipeline runs only when AUTOMATION_ENABLED is exactly 'true'."""
    return os.getenv("AUTOMATION_ENABLED") == "true"

def safe_message(exc: Exception) -> str:
    from pipeline.ingest import safe_error
    return safe_error(exc)

@app.function_name(name="pipeline_tick")
@app.timer_trigger(schedule="0 0 */2 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def pipeline_tick_timer(myTimer: func.TimerRequest) -> None:
    """
    Every 2 hours: ingest (at most every 12 h), prefilter, extract, gate and top up within an 8-minute budget.
    Does nothing unless AUTOMATION_ENABLED is 'true'.
    """
    if not automation_enabled():
        logging.info('automation disabled')
        return

    from db.database import SessionLocal
    from pipeline.extract import GeminiClient
    from pipeline.gates import GeminiEmbedClient, RequestsFetcher
    from pipeline.orchestrator import run_pipeline

    db = SessionLocal()
    try:
        summary = run_pipeline(db, GeminiClient(), GeminiEmbedClient(), RequestsFetcher(), PIPELINE_BUDGET_SECONDS)
        logging.info(f"Pipeline tick finished: status={summary['status']} buffer={summary['buffer']} "
                     f"failed_stages={summary['failed_stages']} note={summary['error']}")
    except Exception as e:
        logging.error(f'Pipeline tick failed: {safe_message(e)}')
        raise
    finally:
        db.close()

@app.function_name(name="daily_extraction")
@app.timer_trigger(schedule="0 0 9 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False) 
def daily_extraction_timer(myTimer: func.TimerRequest) -> None:
    """
    Azure Function Timer Trigger for daily Step 3 extraction.
    Runs daily at 9:00 AM UTC.
    Processes HN and Stack Exchange backlog until cleared.
    With AUTOMATION_ENABLED 'true' it does nothing: pipeline_tick handles ingestion and extraction.
    """
    if automation_enabled():
        logging.info('daily_extraction: automation enabled, pipeline_tick handles ingestion and extraction')
        return

    if myTimer.past_due:
        logging.info('The timer is past due!')
    
    logging.info('Starting daily extraction...')
    
    try:
        # Import and run extraction
        from ingestion.hn_ingest import fetch_hn_ideas_via_context_stitching
        from ingestion.stackexchange_ingest import fetch_softwarerecs_ideas
        
        # Run HN extraction (limited by quota)
        logging.info('Running HN extraction...')
        fetch_hn_ideas_via_context_stitching()
        
        # Run Stack Exchange extraction (limited by quota)
        logging.info('Running Stack Exchange extraction...')
        fetch_softwarerecs_ideas()
        
        logging.info('Daily extraction completed successfully')
    
    except Exception as e:
        logging.error(f'Daily extraction failed: {str(e)}')
        raise

@app.function_name(name="daily_publish")
@app.timer_trigger(schedule="0 0 10 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False)
def daily_publish_timer(myTimer: func.TimerRequest) -> None:
    """
    Azure Function Timer Trigger for daily publishing.
    Runs daily at 10:00 AM UTC (1 hour after extraction).
    With AUTOMATION_ENABLED 'true': publishes gate-passed ideas through pipeline/publish.py.
    Otherwise: promotes up to 5 ready_to_publish records to briefs table.
    """
    if myTimer.past_due:
        logging.info('The timer is past due!')
    
    if automation_enabled():
        logging.info('Starting automated publish...')
        from db.database import SessionLocal
        from pipeline.gates import GeminiEmbedClient
        from pipeline.publish import run_publish

        db = SessionLocal()
        try:
            summary = run_publish(db, GeminiEmbedClient())
            logging.info(f"Automated publish finished: status={summary['status']} day={summary['day']} "
                         f"published={summary['published']} note={summary.get('note')} "
                         f"buffer_after={summary.get('buffer_after')}")
        except Exception as e:
            logging.error(f'Automated publish failed: {safe_message(e)}')
            raise
        finally:
            db.close()
        return

    logging.info('Starting daily publish...')
    
    try:
        # Import and run publish function
        from daily_publish_to_briefs import daily_publish_to_briefs
        
        # Publish up to 5 ready_to_publish records
        promoted = daily_publish_to_briefs(limit=5)
        
        logging.info(f'Daily publish completed: {promoted} briefs promoted')
    
    except Exception as e:
        logging.error(f'Daily publish failed: {str(e)}')
        raise
