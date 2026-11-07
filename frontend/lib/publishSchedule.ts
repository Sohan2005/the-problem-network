// Must match the daily_publish timer in functions/scheduled_pipeline/function_app.py ("0 0 10 * * *", UTC).
export const PUBLISH_SCHEDULE = {
  hourUtc: 10,
  minuteUtc: 0,
  graceHours: 3,
};
