import pytest

from app.services.validation import DatasetValidationError, UploadLimits, check_extension, read_and_validate_csv
from helpers import LIMITS, write_csv


def expect_error(path, code, limits=LIMITS):
    with pytest.raises(DatasetValidationError) as caught:
        read_and_validate_csv(path, limits)
    assert caught.value.code == code
    return caught.value


def test_valid_csv_is_read(tmp_path):
    result = read_and_validate_csv(write_csv(tmp_path / "a.csv", "x,y\n1,2\n3,4\n"), LIMITS)
    assert list(result.frame.columns) == ["x", "y"]
    assert len(result.frame) == 2
    assert result.encoding == "utf-8"


@pytest.mark.parametrize("name", ["data.xlsx", "data.txt", "data.csv.exe", "data"])
def test_non_csv_extension_is_rejected(name):
    with pytest.raises(DatasetValidationError) as caught:
        check_extension(name)
    assert caught.value.status_code == 415


def test_extension_check_is_case_insensitive():
    check_extension("DATA.CSV")


def test_empty_file(tmp_path):
    expect_error(write_csv(tmp_path / "e.csv", ""), "empty_file")


def test_whitespace_only_file(tmp_path):
    expect_error(write_csv(tmp_path / "w.csv", "  \n \n"), "empty_file")


def test_header_without_rows(tmp_path):
    expect_error(write_csv(tmp_path / "h.csv", "a,b\n"), "no_data_rows")


def test_numeric_first_row_means_missing_header(tmp_path):
    expect_error(write_csv(tmp_path / "n.csv", "1,2,3\n4,5,6\n"), "missing_header")


def test_blank_column_name(tmp_path):
    expect_error(write_csv(tmp_path / "b.csv", "a,,c\n1,2,3\n"), "missing_header")


def test_duplicate_column_names_are_case_insensitive(tmp_path):
    error = expect_error(write_csv(tmp_path / "d.csv", "cpu,CPU\n1,2\n"), "duplicate_columns")
    assert "CPU" in error.message


def test_row_with_too_many_fields(tmp_path):
    expect_error(write_csv(tmp_path / "m.csv", "a,b\n1,2\n3,4,5\n"), "malformed_csv")


def test_short_rows_become_a_warning_not_an_error(tmp_path):
    result = read_and_validate_csv(write_csv(tmp_path / "s.csv", "a,b,c\n1,2,3\n4,5\n"), LIMITS)
    assert any("fewer fields" in warning for warning in result.warnings)


def test_binary_file_is_rejected(tmp_path):
    expect_error(write_csv(tmp_path / "x.csv", b"PK\x03\x04\x00\x00binary"), "not_a_text_file")


def test_utf8_bom_and_utf16_are_supported(tmp_path):
    bom = read_and_validate_csv(write_csv(tmp_path / "bom.csv", "\ufeffname,v\nä,1\n".encode("utf-8")), LIMITS)
    assert bom.frame.columns[0] == "name"
    utf16 = read_and_validate_csv(write_csv(tmp_path / "u16.csv", "name,v\nä,1\n".encode("utf-16")), LIMITS)
    assert utf16.encoding == "utf-16"
    assert utf16.frame.iloc[0, 0] == "ä"


def test_windows_1252_is_accepted_with_a_warning(tmp_path):
    result = read_and_validate_csv(write_csv(tmp_path / "w.csv", "city,v\nZürich,1\n".encode("cp1252")), LIMITS)
    assert result.encoding == "cp1252"
    assert result.warnings


def test_unsupported_encoding(tmp_path):
    expect_error(write_csv(tmp_path / "bad.csv", b"a,b\n\x81\x8d,1\n"), "unsupported_encoding")


def test_semicolon_delimiter_is_detected(tmp_path):
    result = read_and_validate_csv(write_csv(tmp_path / "s.csv", "a;b\n1;2\n3;4\n"), LIMITS)
    assert result.delimiter == ";"


def test_limits(tmp_path):
    small = UploadLimits(max_bytes=20, max_rows=1, max_columns=1)
    error = expect_error(write_csv(tmp_path / "big.csv", "a\n" + "1\n" * 30), "file_too_large", small)
    assert error.status_code == 413
    expect_error(write_csv(tmp_path / "rows.csv", "a\n1\n2\n"), "too_many_rows", UploadLimits(10**6, 1, 5))
    expect_error(write_csv(tmp_path / "cols.csv", "a,b\n1,2\n"), "too_many_columns", UploadLimits(10**6, 10, 1))
