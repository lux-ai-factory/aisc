def test_slugs_are_safe_for_urls_and_secret_keys():
    from aisc_connectors.slug import secret_key, slugify

    assert slugify("MCAS lite, prod!") == "mcas_lite_prod"
    assert slugify("  ") == "connector"
    assert slugify("9 lives") == "c_9_lives"
    assert secret_key("mcas_lite_prod") == "CONNECTOR_MCAS_LITE_PROD_TOKEN"
    assert len(slugify("x" * 200)) == 40


def test_a_digit_leading_60_char_name_does_not_end_in_underscore():
    from aisc_connectors.slug import slugify

    # After lowering and substitution this is "5" + 36 a's + "_" + 22 b's (60 chars).
    # slugify's [:40] slice on "c_" + slug lands exactly on that "_" unless it is
    # stripped again after the digit-prefix truncation.
    name = "5" + "a" * 36 + " " + "b" * 22
    assert len(name) == 60

    result = slugify(name)

    assert not result.endswith("_")
    assert result == "c_5" + "a" * 36
