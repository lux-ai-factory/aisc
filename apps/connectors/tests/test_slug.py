def test_slugs_are_safe_for_urls_and_secret_keys():
    from aisc_connectors.slug import secret_key, slugify

    assert slugify("MCAS lite, prod!") == "mcas_lite_prod"
    assert slugify("  ") == "connector"
    assert slugify("9 lives") == "c_9_lives"
    assert secret_key("mcas_lite_prod") == "CONNECTOR_MCAS_LITE_PROD_TOKEN"
    assert len(slugify("x" * 200)) == 40
