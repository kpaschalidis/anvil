from scout.sources.producthunt import _extract_post_slugs, _extract_product_slugs


class TestProductHuntHelpers:
    def test_extract_post_slugs(self):
        hrefs = [
            "/posts/acme",
            "/posts/acme?ref=search",
            "https://www.producthunt.com/posts/beta",
            "/collections/foo",
            None,
            "",
        ]
        assert _extract_post_slugs(hrefs) == ["acme", "beta"]

    def test_extract_product_slugs(self):
        hrefs = [
            "/products/coverage-cat",
            "/products/coverage-cat/reviews",
            "/products/coverage-cat?ref=search",
            "https://www.producthunt.com/products/formstory-io",
            "/posts/ignored",
        ]
        assert _extract_product_slugs(hrefs) == ["coverage-cat", "formstory-io"]
