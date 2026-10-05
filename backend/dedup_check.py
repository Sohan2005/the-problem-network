import os
import sys
from dotenv import load_dotenv
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.models import RawIdea

# Load .env from project root (relative to this script)
project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
env_path = os.path.join(project_root, '.env')
load_dotenv(env_path)

def check_within_batch_duplicates(ideas, db_session):
    """
    Check for duplicates within the current batch of candidates.
    Automatically resolves by keeping the lowest ID in each duplicate group.
    
    Returns:
    - kept_ids: set of IDs to keep (lowest ID from each duplicate group)
    - excluded_info: list of tuples (excluded_id, kept_id, similarity, excluded_title, kept_title)
    """
    import numpy as np
    from llm.translate import generate_embedding
    
    # Generate embeddings for all ideas
    embeddings = []
    for idea in ideas:
        title = idea.extracted_title if idea.extracted_title else idea.raw_title
        problem = idea.problem_summary if idea.problem_summary else ""
        
        # Use rescoped version if available
        if idea.is_valid_idea == "needs_rescope" and idea.rescoped_version:
            title = idea.rescoped_version.get('title', title)
            problem = idea.rescoped_version.get('problem_summary', problem)
        
        combined_text = f"{title} {problem}"
        embedding = generate_embedding(combined_text)
        embeddings.append((idea.id, title, embedding))
    
    # Check pairwise similarity and build duplicate groups
    threshold = 0.75
    id_to_title = {id: title for id, title, _ in embeddings}
    
    # Build adjacency list for duplicate groups
    groups = []
    seen = set()
    in_duplicate_group = set()
    
    for i in range(len(embeddings)):
        id1, title1, emb1 = embeddings[i]
        if id1 in seen:
            continue
        
        # Start a new group with this ID
        group = [id1]
        seen.add(id1)
        
        # Find all IDs similar to this one
        for j in range(len(embeddings)):
            if i == j:
                continue
            id2, title2, emb2 = embeddings[j]
            
            if id2 in seen:
                continue
            
            # Calculate cosine similarity
            emb1_array = np.array(emb1)
            emb2_array = np.array(emb2)
            similarity = np.dot(emb1_array, emb2_array) / (np.linalg.norm(emb1_array) * np.linalg.norm(emb2_array))
            
            if similarity >= threshold:
                group.append(id2)
                seen.add(id2)
        
        if len(group) > 1:
            groups.append(group)
            in_duplicate_group.update(group)
    
    # Resolve groups: keep lowest ID, exclude others
    kept_ids = set()
    excluded_info = []
    
    for group in groups:
        kept_id = min(group)
        kept_ids.add(kept_id)
        
        for excluded_id in group:
            if excluded_id != kept_id:
                # Calculate similarity for logging
                idx1 = next(i for i, (id, _, _) in enumerate(embeddings) if id == excluded_id)
                idx2 = next(i for i, (id, _, _) in enumerate(embeddings) if id == kept_id)
                
                emb1 = embeddings[idx1][2]
                emb2 = embeddings[idx2][2]
                emb1_array = np.array(emb1)
                emb2_array = np.array(emb2)
                similarity = np.dot(emb1_array, emb2_array) / (np.linalg.norm(emb1_array) * np.linalg.norm(emb2_array))
                
                excluded_info.append((excluded_id, kept_id, similarity, id_to_title[excluded_id], id_to_title[kept_id]))
    
    # Add all non-duplicate IDs to kept_ids
    all_ids = {id for id, _, _ in embeddings}
    kept_ids.update(all_ids - in_duplicate_group)
    
    return kept_ids, excluded_info

def check_duplicate(title, problem_summary, db_session):
    """
    Check if a candidate is a duplicate of existing live briefs using pgvector similarity.
    
    Returns:
    - (None, None) if no duplicate found (similarity < 0.75)
    - (brief_id, similarity_score) if gray zone duplicate (0.75 <= similarity <= 0.88)
    - (brief_id, similarity_score) if high similarity duplicate (similarity > 0.88)
    """
    from llm.translate import generate_embedding
    
    # Generate embedding for candidate
    combined_text = f"{title} {problem_summary}"
    embedding = generate_embedding(combined_text)
    
    # Convert to pgvector format
    embedding_str = f"[{','.join(map(str, embedding))}]"
    
    # Search for similar briefs in live briefs table using raw SQL
    query = text("""
        SELECT id, title, 1 - (embedding <=> CAST(:embedding AS vector)) as similarity
        FROM briefs
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> CAST(:embedding AS vector)
        LIMIT 1
    """)
    
    result = db_session.execute(query, {"embedding": embedding_str}).fetchone()
    
    if not result:
        return None, None
    
    brief_id, brief_title, similarity = result
    
    if similarity > 0.88:
        # High similarity - reject as duplicate
        return brief_id, similarity
    elif similarity >= 0.75:
        # Gray zone - flag for review
        return brief_id, similarity
    else:
        # No duplicate
        return None, None

def log_duplicate_candidate(raw_idea_id, matched_brief_id, similarity_score, raw_title, matched_brief_title):
    """Log a rejected duplicate candidate to the duplicate_candidates table"""
    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("""
            INSERT INTO duplicate_candidates (raw_idea_id, matched_brief_id, similarity_score, raw_title, matched_brief_title)
            VALUES (:raw_idea_id, :matched_brief_id, :similarity_score, :raw_title, :matched_brief_title)
        """), {
            "raw_idea_id": raw_idea_id,
            "matched_brief_id": matched_brief_id,
            "similarity_score": similarity_score,
            "raw_title": raw_title,
            "matched_brief_title": matched_brief_title
        })
        db.commit()
    except Exception as e:
        print(f"Error logging duplicate candidate: {e}")
        db.rollback()
    finally:
        db.close()
