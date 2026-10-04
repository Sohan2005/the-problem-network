import azure.functions as func
import logging
import sys
import os

# Add backend to path for imports
backend_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend'))
if backend_path not in sys.path:
    sys.path.insert(0, backend_path)

app = func.FunctionApp()

@app.function_name(name="daily_extraction")
@app.timer_trigger(schedule="0 0 9 * * *", arg_name="myTimer", run_on_startup=False,
                   use_monitor=False) 
def daily_extraction_timer(myTimer: func.TimerRequest) -> None:
    """
    Azure Function Timer Trigger for daily Step 3 extraction.
    Runs daily at 9:00 AM UTC.
    Processes HN and Stack Exchange backlog until cleared.
    """
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
    Promotes up to 10 ready_to_publish records to briefs table.
    """
    if myTimer.past_due:
        logging.info('The timer is past due!')
    
    logging.info('Starting daily publish...')
    
    try:
        # Import and run publish function
        from daily_publish_to_briefs import daily_publish_to_briefs
        
        # Publish up to 10 ready_to_publish records
        promoted = daily_publish_to_briefs(limit=10)
        
        logging.info(f'Daily publish completed: {promoted} briefs promoted')
    
    except Exception as e:
        logging.error(f'Daily publish failed: {str(e)}')
        raise
