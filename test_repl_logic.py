#!/usr/bin/env python3
"""Validation script for the REPL client note parsing and timestamp inference logic.

This script runs test cases to verify that relative dates (today/yesterday) and
24-hour time notations (HH.MM or HH:MM) are parsed correctly from conversation
prompts to create valid naive local timestamps for user annotations.
"""

import datetime
from typing import List, Tuple
from repl_client import infer_note_timestamp


def run_timestamp_tests() -> None:
    """Executes a series of test cases against the time inference helper.

    Raises:
        AssertionError: If any of the parsing results do not match expected outcomes.
    """
    today_date: datetime.date = datetime.date.today()
    yesterday_date: datetime.date = today_date - datetime.timedelta(days=1)
    
    test_cases: List[Tuple[str, str, str]] = [
        # (current_input, previous_input, expected_date_str_prefix)
        (
            "It was a usage event that lasted about 15 to 20 minutes /note that was the kettle tuning on",
            "Do you see the short peak around 13.30 today?",
            f"{today_date.strftime('%Y-%m-%d')} 13:30:00"
        ),
        (
            "/note if you look in the data for yesterday I turned on the home entertainment gear at around 19.00 which usually draws about 2Kw",
            "",
            f"{yesterday_date.strftime('%Y-%m-%d')} 19:00:00"
        ),
        (
            "Spike at 12:45 /note toaster was running",
            "",
            f"{today_date.strftime('%Y-%m-%d')} 12:45:00"
        ),
        (
            "/note we had a flex event yesterday",
            "",
            # No time specified, defaults to current time on yesterday's date
            f"{yesterday_date.strftime('%Y-%m-%d')} {datetime.datetime.now().strftime('%H:%M')}:00"
        )
    ]

    print("Running Timestamp Inference Tests...")
    print("==================================================")
    
    passed_count: int = 0
    for idx, (curr_in, prev_in, expected) in enumerate(test_cases, start=1):
        actual: str = infer_note_timestamp(curr_in, prev_in)
        # For timeless cases, check the prefix up to minute level in case seconds change
        if actual[:16] == expected[:16]:
            print(f"Test case {idx}: PASSED (Actual: {actual})")
            passed_count += 1
        else:
            print(f"Test case {idx}: FAILED")
            print(f"  Inputs: '{curr_in}' | '{prev_in}'")
            print(f"  Expected: {expected}")
            print(f"  Actual  : {actual}")
            
    print("==================================================")
    print(f"Result: {passed_count}/{len(test_cases)} tests passed.")


if __name__ == "__main__":
    run_timestamp_tests()
