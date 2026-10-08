import sys

sys.exit("promote_to_briefs.py is retired and must not be run: briefs are published by pipeline/publish.py "
         "(run_publish, called from the daily_publish timer).")

import os
import json
from dotenv import load_dotenv
import psycopg2

load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL")

def promote_to_briefs():
    """Promote 18 approved records from raw_ideas to briefs table"""
    
    conn = psycopg2.connect(DATABASE_URL)
    try:
        cursor = conn.cursor()
        
        # Get all approved records
        cursor.execute("""
            SELECT id, source, source_url, raw_text, 
                   is_valid_idea, extracted_title, problem_summary, target_user,
                   suggested_features, difficulty_estimate, suggested_tech_stack,
                   learning_outcomes, rescoped_version
            FROM raw_ideas
            WHERE is_valid_idea IN ('true', 'needs_rescope')
            AND processed_at IS NOT NULL
            ORDER BY id;
        """)
        records = cursor.fetchall()
        
        print(f"Found {len(records)} approved records to promote\n")
        
        promoted_count = 0
        
        for row in records:
            raw_id, source, source_url, raw_text, is_valid_idea, extracted_title, problem_summary, target_user, features, difficulty, tech_stack, learning, rescoped_version = row
            
            # Determine which fields to use (rescoped or direct)
            if is_valid_idea == 'needs_rescope' and rescoped_version:
                title = rescoped_version.get('title')
                problem = rescoped_version.get('problem_summary')
                target = rescoped_version.get('target_user')
                features_list = rescoped_version.get('suggested_features', [])
                diff = rescoped_version.get('difficulty_estimate')
                tech_list = rescoped_version.get('suggested_tech_stack', [])
                learning_list = rescoped_version.get('learning_outcomes', [])
            else:
                title = extracted_title
                problem = problem_summary
                target = target_user
                features_list = features if features else []
                diff = difficulty
                tech_list = tech_stack if tech_stack else []
                learning_list = learning if learning else []
            
            # Convert lists to strings for storage
            features_str = json.dumps(features_list) if features_list else None
            tech_str = json.dumps(tech_list) if tech_list else None
            learning_str = json.dumps(learning_list) if learning_list else None
            
            # Insert into problems table
            cursor.execute("""
                INSERT INTO problems (source, source_url, raw_text, ingested_at)
                VALUES (%s, %s, %s, NOW())
                RETURNING id;
            """, (source, source_url, raw_text))
            problem_id = cursor.fetchone()[0]
            
            # Insert into briefs table
            cursor.execute("""
                INSERT INTO briefs (problem_id, title, difficulty, core_task, recommended_stack, created_at)
                VALUES (%s, %s, %s, %s, %s, NOW());
            """, (problem_id, title, diff, problem, tech_str))
            
            promoted_count += 1
            print(f"[{promoted_count}] Promoted raw_id {raw_id} to brief_id {problem_id}: {title}")
        
        conn.commit()
        print(f"\n=== Promotion Complete ===")
        print(f"Promoted {promoted_count} records to briefs table")
        
    except Exception as e:
        print(f"Error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    promote_to_briefs()
