import os
import sys
from datetime import datetime
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.models import RawIdea
from dedup_check import check_within_batch_duplicates

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def export_for_review(output_file="step6_review_export_latest.md"):
    """
    Export valid ideas that are NOT yet ready_to_publish for manual review.
    Format similar to step6_review_export.md for easy batch approval.
    """
    
    db = SessionLocal()
    try:
        # Get valid ideas not yet ready_to_publish
        records = db.query(RawIdea).filter(
            RawIdea.is_valid_idea.in_(['true', 'needs_rescope']),
            RawIdea.processed_at != None,
            (RawIdea.ready_to_publish == None) | (RawIdea.ready_to_publish == False)
        ).order_by(RawIdea.processed_at.desc()).all()
        
        if not records:
            print("No valid ideas pending review found.")
            return
        
        print(f"Found {len(records)} valid ideas pending review\n")
        
        # Check for within-batch duplicates and auto-resolve
        kept_ids, excluded_info = check_within_batch_duplicates(records, db)
        print(f"Auto-resolved {len(excluded_info)} within-batch duplicates (kept {len(kept_ids)} unique IDs)")
        
        # Log excluded duplicates to file
        if excluded_info:
            with open('duplicates_resolved.log', 'w', encoding='utf-8') as log:
                log.write(f"# Within-Batch Duplicate Auto-Resolution Log\n")
                log.write(f"# Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
                log.write(f"Total excluded: {len(excluded_info)}\n\n")
                for excluded_id, kept_id, similarity, excluded_title, kept_title in excluded_info:
                    log.write(f"Excluded ID {excluded_id} -> Kept ID {kept_id} (similarity: {similarity:.3f})\n")
                    log.write(f"  Excluded: {excluded_title}\n")
                    log.write(f"  Kept: {kept_title}\n\n")
            print(f"Logged excluded duplicates to duplicates_resolved.log")
        
        # Filter records to only include kept IDs
        filtered_records = [r for r in records if r.id in kept_ids]
        print(f"Filtered to {len(filtered_records)} ideas for review\n")
        
        # Count by source
        source_counts = {}
        for record in filtered_records:
            source = record.source
            source_counts[source] = source_counts.get(source, 0) + 1
        
        # Create lookup for auto-resolution notes
        kept_to_excluded = {}
        for excluded_id, kept_id, similarity, _, _ in excluded_info:
            if kept_id not in kept_to_excluded:
                kept_to_excluded[kept_id] = []
            kept_to_excluded[kept_id].append(excluded_id)
        
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# Step 6 Review Export - {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n\n")
            f.write(f"Total pending review: {len(filtered_records)} (auto-resolved {len(excluded_info)} within-batch duplicates)\n\n")
            f.write("## Source Breakdown\n\n")
            for source, count in source_counts.items():
                f.write(f"- {source}: {count}\n")
            f.write("\n")
            f.write("## Instructions\n\n")
            f.write("1. Review each idea below\n")
            f.write("2. To approve for publishing, add the ID to the APPROVED_IDS list at the bottom\n")
            f.write("3. Run: `python mark_ready_to_publish.py` to batch approve\n")
            f.write("4. See duplicates_resolved.log for auto-resolved within-batch duplicates\n\n")
            f.write("---\n\n")
            
            for record in filtered_records:
                raw_id = record.id
                source = record.source
                raw_title = record.raw_title
                extracted_title = record.extracted_title
                problem_summary = record.problem_summary
                target_user = record.target_user
                difficulty = record.difficulty_estimate
                is_valid_idea = record.is_valid_idea
                rescoped_version = record.rescoped_version
                source_date = record.source_date
                duplicate_of_brief_id = record.duplicate_of_brief_id
                similarity_score = record.similarity_score
                suggested_features = record.suggested_features
                suggested_tech_stack = record.suggested_tech_stack
                learning_outcomes = record.learning_outcomes
                source_url = record.source_url
                
                # Determine display title (rescoped or direct)
                if is_valid_idea == 'needs_rescope' and rescoped_version:
                    display_title = rescoped_version.get('title', extracted_title)
                    display_problem = rescoped_version.get('problem_summary', problem_summary)
                    display_target = rescoped_version.get('target_user', target_user)
                    display_difficulty = rescoped_version.get('difficulty_estimate', difficulty)
                    display_features = rescoped_version.get('suggested_features', suggested_features)
                    display_tech_stack = rescoped_version.get('suggested_tech_stack', suggested_tech_stack)
                    display_learning = rescoped_version.get('learning_outcomes', learning_outcomes)
                    status = "[RESCOPED]"
                else:
                    display_title = extracted_title
                    display_problem = problem_summary
                    display_target = target_user
                    display_difficulty = difficulty
                    display_features = suggested_features
                    display_tech_stack = suggested_tech_stack
                    display_learning = learning_outcomes
                    status = "[VALID]"
                
                f.write(f"## ID {raw_id} {status}\n\n")
                f.write(f"**Source Platform:** {source}\n")
                f.write(f"**Source URL:** {source_url}\n")
                f.write(f"**Original Title:** {raw_title}\n")
                f.write(f"**Extracted Title:** {display_title}\n")
                f.write(f"**Difficulty:** {display_difficulty}\n")
                f.write(f"**Target User:** {display_target}\n")
                f.write(f"**Source Date:** {source_date.strftime('%Y-%m-%d') if source_date else 'N/A'}\n")
                
                # Surface duplicate flag if present (from live briefs)
                if duplicate_of_brief_id and similarity_score:
                    f.write(f"**⚠️ DUPLICATE FLAG:** Similar to existing brief ID {duplicate_of_brief_id} (similarity: {similarity_score:.2f})\n")
                
                # Surface auto-resolution note if this ID kept others
                if raw_id in kept_to_excluded:
                    excluded_ids = kept_to_excluded[raw_id]
                    f.write(f"**Auto-resolved:** Excluded duplicate ID(s) {', '.join(map(str, excluded_ids))} (see duplicates_resolved.log)\n")
                
                f.write(f"\n**Problem Summary:**\n{display_problem}\n\n")
                
                if display_features:
                    f.write(f"**Suggested Features:**\n")
                    for feature in display_features:
                        f.write(f"- {feature}\n")
                    f.write("\n")
                
                if display_tech_stack:
                    f.write(f"**Suggested Tech Stack:**\n")
                    for tech in display_tech_stack:
                        f.write(f"- {tech}\n")
                    f.write("\n")
                
                if display_learning:
                    f.write(f"**Learning Outcomes:**\n")
                    for learning in display_learning:
                        f.write(f"- {learning}\n")
                    f.write("\n")
                
                f.write("---\n\n")
            
            f.write("## APPROVED_IDS\n\n")
            f.write("# Add IDs to approve (comma-separated, e.g.: 123, 456, 789)\n")
            f.write("APPROVED_IDS = []\n")
        
        print(f"Exported {len(filtered_records)} ideas to {output_file}")
        print(f"Source breakdown: {source_counts}")
        print(f"Review the file, add approved IDs, then run: python mark_ready_to_publish.py")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    export_for_review()
