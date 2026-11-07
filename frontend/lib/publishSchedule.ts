// Must match the daily_publish timer in functions/scheduled_pipeline/function_app.py ("0 0 10 * * *", UTC).
export const PUBLISH_SCHEDULE = {
  hourUtc: 10,
  minuteUtc: 0,
  cadenceHours: 24,
  graceHours: 3,
};

// A posting younger than one publish cycle plus the grace period means the pipeline is on schedule.
export const LIVE_WINDOW_MS = (PUBLISH_SCHEDULE.cadenceHours + PUBLISH_SCHEDULE.graceHours) * 60 * 60 * 1000;
