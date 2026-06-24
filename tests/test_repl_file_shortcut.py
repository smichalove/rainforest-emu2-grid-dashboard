import os
import tempfile
import pytest
from repl_client import process_file_attachments

def test_no_file_attachment():
    prompt = "What is the battery state of charge?"
    updated, success = process_file_attachments(prompt)
    assert success is True
    assert updated == prompt

def test_valid_file_attachment():
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w+", delete=False, encoding="utf-8") as f:
        f.write("System online. Grid import: 2.5 kW.")
        f_path = f.name
        
    try:
        prompt = f"Analyze this /file {f_path} and summarize."
        updated, success = process_file_attachments(prompt)
        assert success is True
        assert "Analyze this and summarize." in updated
        assert "=== ATTACHED FILE:" in updated
        assert "System online. Grid import: 2.5 kW." in updated
    finally:
        os.remove(f_path)

def test_multiple_file_attachments():
    with tempfile.NamedTemporaryFile(suffix=".log", mode="w+", delete=False, encoding="utf-8") as f1:
        f1.write("Error: Battery high temp")
        f1_path = f1.name
    with tempfile.NamedTemporaryFile(suffix=".csv", mode="w+", delete=False, encoding="utf-8") as f2:
        f2.write("14:00,1.2")
        f2_path = f2.name
        
    try:
        prompt = f"/file {f1_path} check this /file {f2_path} too"
        updated, success = process_file_attachments(prompt)
        assert success is True
        assert "check this too" in updated
        assert "Error: Battery high temp" in updated
        assert "14:00,1.2" in updated
    finally:
        os.remove(f1_path)
        os.remove(f2_path)

def test_quoted_file_path_with_spaces():
    temp_dir = tempfile.mkdtemp()
    f_path = os.path.join(temp_dir, "my log file.txt")
    with open(f_path, "w", encoding="utf-8") as f:
        f.write("Log contents here.")
        
    try:
        prompt = f'Explain this log /file "{f_path}" please'
        updated, success = process_file_attachments(prompt)
        assert success is True
        assert "Explain this log please" in updated
        assert "Log contents here." in updated
    finally:
        os.remove(f_path)
        os.rmdir(temp_dir)

def test_file_not_found():
    prompt = "/file non_existent_file_xyz.txt"
    updated, success = process_file_attachments(prompt)
    assert success is False
    assert updated is None

def test_path_is_directory():
    temp_dir = tempfile.mkdtemp()
    try:
        prompt = f"/file {temp_dir}"
        updated, success = process_file_attachments(prompt)
        assert success is False
        assert updated is None
    finally:
        os.rmdir(temp_dir)

def test_pdf_rejection():
    with tempfile.NamedTemporaryFile(suffix=".pdf", mode="w+", delete=False) as f:
        f_path = f.name
    try:
        prompt = f"Read this PDF /file {f_path}"
        updated, success = process_file_attachments(prompt)
        assert success is False
        assert updated is None
    finally:
        os.remove(f_path)

def test_unsupported_extension():
    with tempfile.NamedTemporaryFile(suffix=".png", mode="w+", delete=False) as f:
        f_path = f.name
    try:
        prompt = f"Load image /file {f_path}"
        updated, success = process_file_attachments(prompt)
        assert success is False
        assert updated is None
    finally:
        os.remove(f_path)

def test_pse_csv_attachment():
    # Verify we can attach the actual pse electric CSV file
    pse_file = "pse_electric_billing_billing_data_Service 1_1_2023-09-07_to_2026-05-05.csv"
    assert os.path.exists(pse_file)
    
    prompt = f'Analyze this billing data /file "{pse_file}"'
    updated, success = process_file_attachments(prompt)
    assert success is True
    assert "Analyze this billing data" in updated
    assert "STEVEN MICHALOVE" in updated
    assert "Electric billing,2023-09-07" in updated

def test_backslash_escaped_path():
    pse_file_escaped = "pse_electric_billing_billing_data_Service\\ 1_1_2023-09-07_to_2026-05-05.csv"
    prompt = f"Analyze this billing data /file {pse_file_escaped}"
    updated, success = process_file_attachments(prompt)
    assert success is True
    assert "Analyze this billing data" in updated
    assert "STEVEN MICHALOVE" in updated
    assert "Electric billing,2023-09-07" in updated


