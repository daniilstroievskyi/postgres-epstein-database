"""Required edge cases on synthetic values, independent of corpus contents."""
import math
import unittest
from decimal import Decimal
from scripts.z1_transform import parse_date, parse_json, parse_amount, normalize, content_identity, equal_records


class TransformationTest(unittest.TestCase):
    def test_invalid_missing_partial_dates_and_no_invented_zone(self):
        self.assertEqual(parse_date(None)["state"],"missing")
        self.assertEqual(parse_date("2020-02-30")["state"],"invalid")
        year=parse_date("2015")
        self.assertEqual((year["year"],year["month"],year["day"]),(2015,None,None))
        month=parse_date("2015-02")
        self.assertEqual((month["month"],month["day"]),(2,None))
        self.assertEqual(parse_date("circa 2015")["state"],"unparsed")
        local=parse_date("2020-01-01 12:30:00",timestamp_only=True)
        self.assertIsNone(local["instant"])
        self.assertIsNone(local["local_timestamp"].tzinfo)
        zoned=parse_date("2020-01-01T12:30:00+02:00",timestamp_only=True)
        self.assertIsNotNone(zoned["instant"].tzinfo)
        self.assertEqual(parse_date("2020-01-01T12:30:00+01:99")["state"],"invalid")

    def test_json_null_missing_invalid_arrays_and_key_absence(self):
        self.assertEqual(parse_json(None)[1],"missing")
        self.assertEqual(parse_json("null")[0:2],("null","json_null"))
        self.assertEqual(parse_json("{")[1],"invalid")
        self.assertEqual(parse_json('{"subject":null}')[3],{"subject":None})
        self.assertNotIn("subject",parse_json("{}")[3])
        array=parse_json("[]","object")
        self.assertEqual(array[1],"valid")
        self.assertIn("json_unexpected_shape",array[2])
        self.assertEqual(parse_json('{"n":NaN}')[1],"invalid")
        self.assertEqual(parse_json('"\\u0000"')[1],"invalid")
        self.assertEqual(parse_json('{"a":"\\u0000","a":"safe"}')[1],"invalid")
        self.assertIn("json_duplicate_key",parse_json('{"a":1,"a":2}')[2])

    def test_json_decimal_text_and_money_precision_sign_missing(self):
        raw='{"amount":0.12345678901234567890123456789}'
        self.assertEqual(parse_json(raw)[0],raw)
        self.assertEqual(parse_amount(None),(None,"missing"))
        self.assertEqual(parse_amount(float('nan')),(None,"invalid"))
        self.assertEqual(parse_amount(-0.125),(Decimal('-0.125'),"valid"))
        self.assertEqual(parse_amount(0.1)[0],Decimal.from_float(0.1))

    def test_normalization_is_search_only(self):
        self.assertEqual(normalize("  Stra\u00dfe  TEST "),"strasse test")
        self.assertEqual(normalize("\u00c9"),"\u00e9")
        self.assertIsNone(normalize(None))

    def test_identity_ignores_acquisition_time_not_content(self):
        m={"repo_id":"r","revision":"v","acquired_at":"today","files":[{"path":"a","sha256":"hash","row_count":1}]}
        first=content_identity(m,"schema")
        m["acquired_at"]="tomorrow"
        self.assertEqual(first,content_identity(m,"schema"))
        m["files"][0]["sha256"]="changed"
        self.assertNotEqual(first,content_identity(m,"schema"))

    def test_exact_float_comparison_including_nan_and_signed_zero(self):
        self.assertTrue(equal_records({"v":float('nan')},{"v":float('nan')}))
        self.assertFalse(equal_records({"v":0.0},{"v":-0.0}))


if __name__=="__main__": unittest.main()
