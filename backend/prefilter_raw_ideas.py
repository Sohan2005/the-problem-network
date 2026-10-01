import os
import sys
import re
from dotenv import load_dotenv

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.database import SessionLocal
from db.models import RawIdea

load_dotenv()

def extract_matching_comment(raw_text):
    """Extract the MATCHING COMMENT portion from raw_text"""
    if "MATCHING COMMENT:" in raw_text:
        return raw_text.split("MATCHING COMMENT:")[1].strip()
    return raw_text

def count_words(text):
    """Count words in text (simple split by whitespace)"""
    return len(text.split())

def has_buildable_intent(raw_text):
    """Check if text contains buildable-product intent signals"""
    intent_signals = [
        "idea", "build", "app", "website", "tool", 
        "wish there was", "alternative to", "someone should build",
        "would gladly pay", "i would pay", "shut up and take my money",
        "scratch my own itch", "frustratingly bad", "hate the current options",
        "gap in the market", "surprised no one sells"
    ]
    
    text_lower = raw_text.lower()
    for signal in intent_signals:
        if signal in text_lower:
            return True
    return False

def has_exact_trigger_phrase(raw_text):
    """Check if text contains exact trigger phrase (for word-count exception)"""
    trigger_phrases = [
        "wish there was a tool", "someone should build", "is there a lightweight alternative",
        "gap in the market", "surprised no one sells", "would gladly pay",
        "i would pay monthly", "shut up and take my money", "is there a paid version",
        "scratch my own itch", "frustratingly bad", "hate the current options",
        "why is there no open source alternative", "i ended up writing a script"
    ]
    
    text_lower = raw_text.lower()
    for phrase in trigger_phrases:
        if phrase in text_lower:
            return True
    return False

def is_borderline_opinion(raw_text):
    """Check if comment is a pure opinion/comparison question (borderline case)"""
    borderline_patterns = [
        r"does .+ work as .+", r"can .+ substitute .+", r"is .+ better than .+",
        r"what do you think of .+", r"opinion on .+", r"compare .+ and .+"
    ]
    
    text_lower = raw_text.lower()
    for pattern in borderline_patterns:
        if re.search(pattern, text_lower):
            return True
    return False

def count_words_beyond_phrase(text, phrase):
    """Count words in text excluding the phrase itself"""
    if phrase in text.lower():
        # Remove the phrase and count remaining words
        text_without_phrase = text.lower().replace(phrase, "")
        return len(text_without_phrase.split())
    return len(text.split())

def apply_prefilter():
    """Apply Step 2 heuristic pre-filtering to all raw_ideas"""
    
    db = SessionLocal()
    
    try:
        # Get only currently passed records that were rescued by trigger phrase exception
        raw_ideas = db.query(RawIdea).filter(
            RawIdea.passed_prefilter == True
        ).all()
        
        print(f"Re-evaluating {len(raw_ideas)} passed records with refined exception logic\n")
        
        re_rejected_count = 0
        
        for idea in raw_ideas:
            matching_comment = extract_matching_comment(idea.raw_text)
            word_count = count_words(matching_comment)
            
            # Check if it was previously rescued (short but has trigger phrase)
            if word_count < 40 and has_exact_trigger_phrase(idea.raw_text):
                # Find which trigger phrase matched
                trigger_phrases = [
                    "wish there was a tool", "someone should build", "is there a lightweight alternative",
                    "gap in the market", "surprised no one sells", "would gladly pay",
                    "i would pay monthly", "shut up and take my money", "is there a paid version",
                    "scratch my own itch", "frustratingly bad", "hate the current options",
                    "why is there no open source alternative", "i ended up writing a script"
                ]
                
                matched_phrase = None
                for phrase in trigger_phrases:
                    if phrase in idea.raw_text.lower():
                        matched_phrase = phrase
                        break
                
                if matched_phrase:
                    words_beyond = count_words_beyond_phrase(matching_comment, matched_phrase)
                    
                    if words_beyond < 8:
                        # Re-reject: not enough context beyond trigger phrase
                        idea.passed_prefilter = False
                        idea.prefilter_reject_reason = f"Too short ({word_count} words), insufficient context beyond trigger phrase ({words_beyond} words < 8 minimum)"
                        re_rejected_count += 1
                        print(f"[RE-REJECT] ID {idea.id}: {words_beyond} words beyond trigger phrase '{matched_phrase}'")
                    else:
                        # Keep passed
                        print(f"[KEEP PASSED] ID {idea.id}: {words_beyond} words beyond trigger phrase '{matched_phrase}'")
        
        db.commit()
        
        print(f"\n=== Re-evaluation Summary ===")
        print(f"Re-rejected by refined exception: {re_rejected_count}")
        
        # Get final counts
        final_passed = db.query(RawIdea).filter(RawIdea.passed_prefilter == True).count()
        final_rejected = db.query(RawIdea).filter(RawIdea.passed_prefilter == False).count()
        final_borderline = db.query(RawIdea).filter(RawIdea.passed_prefilter.is_(None)).count()
        
        print(f"\n=== Final Pre-Filter Totals ===")
        print(f"Passed: {final_passed}")
        print(f"Rejected: {final_rejected}")
        print(f"Borderline: {final_borderline}")
        
    finally:
        db.close()

if __name__ == "__main__":
    apply_prefilter()
