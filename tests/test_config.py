"""Tests for configuration settings."""

from weather_copy_bot.config import Settings, get_settings


class TestSettingsDefaults:
    """Test default configuration values."""

    def test_default_poll_interval(self):
        settings = Settings()
        assert settings.poll_interval_ms == 250

    def test_default_max_latency(self):
        settings = Settings()
        assert settings.max_copy_latency_ms == 800

    def test_default_copy_ratio(self):
        settings = Settings()
        assert settings.copy_ratio == 0.25

    def test_default_dry_run(self):
        settings = Settings()
        assert settings.dry_run is True

    def test_default_market_filter(self):
        settings = Settings()
        assert settings.market_filter == "weather"

    def test_default_cors_origins(self):
        settings = Settings()
        assert "http://localhost:5173" in settings.cors_origins


class TestTargetWalletsParsing:
    """Test target_wallets field parsing."""

    def test_empty_string(self):
        settings = Settings(target_wallets="")
        assert settings.target_wallets == []

    def test_comma_separated_string(self):
        settings = Settings(target_wallets="0xabc,0xdef,0xghi")
        assert len(settings.target_wallets) == 3
        assert "0xabc" in settings.target_wallets

    def test_json_list_string(self):
        settings = Settings(target_wallets='["0x111", "0x222"]')
        assert settings.target_wallets == ["0x111", "0x222"]

    def test_list_input(self):
        settings = Settings(target_wallets=["0xaaa", "0xbbb"])
        assert settings.target_wallets == ["0xaaa", "0xbbb"]

    def test_whitespace_handling(self):
        settings = Settings(target_wallets="  0x111 ,  0x222  ")
        assert settings.target_wallets == ["0x111", "0x222"]


class TestCorsOriginsParsing:
    """Test CORS origins field parsing."""

    def test_comma_separated_origins(self):
        settings = Settings(cors_origins="http://localhost:3000,https://app.example.com")
        assert len(settings.cors_origins) == 2
        assert "http://localhost:3000" in settings.cors_origins

    def test_list_origins(self):
        settings = Settings(cors_origins=["https://a.com", "https://b.com"])
        assert settings.cors_origins == ["https://a.com", "https://b.com"]

    def test_empty_cors_fallback(self):
        settings = Settings(cors_origins="")
        assert settings.cors_origins == ["http://localhost:5173"]


class TestLiveTradingEnabled:
    """Test live trading enablement logic."""

    def test_live_disabled_by_default(self):
        settings = Settings()
        assert settings.live_trading_enabled is False

    def test_live_disabled_without_key(self):
        settings = Settings(dry_run=False)
        assert settings.live_trading_enabled is False

    def test_live_disabled_dry_run_true(self):
        settings = Settings(dry_run=True, polymarket_private_key="0xsecret")
        assert settings.live_trading_enabled is False

    def test_live_enabled_with_key_and_dry_run_false(self):
        settings = Settings(dry_run=False, polymarket_private_key="0xsecret")
        assert settings.live_trading_enabled is True


class TestApiSettings:
    """Test API server settings."""

    def test_default_api_host(self):
        settings = Settings()
        assert settings.api_host == "0.0.0.0"

    def test_default_api_port(self):
        settings = Settings()
        assert settings.api_port == 8000


class TestHostsConfiguration:
    """Test external API host defaults."""

    def test_default_clob_host(self):
        settings = Settings()
        assert "clob.polymarket.com" in settings.clob_host

    def test_default_gamma_host(self):
        settings = Settings()
        assert "gamma-api.polymarket.com" in settings.gamma_host

    def test_default_data_api_host(self):
        settings = Settings()
        assert "data-api.polymarket.com" in settings.data_api_host

    def test_default_thegraph_api_key_empty(self):
        settings = Settings()
        assert settings.thegraph_api_key == ""

    def test_thegraph_api_key_from_env(self):
        settings = Settings(thegraph_api_key="subgraph_key_123")
        assert settings.thegraph_api_key == "subgraph_key_123"


class TestGetSettingsCache:
    """Test settings caching."""

    def test_get_settings_cached(self):
        get_settings.cache_clear()
        settings1 = get_settings()
        settings2 = get_settings()
        assert settings1 is settings2

    def test_cache_clear(self):
        get_settings.cache_clear()
        settings1 = get_settings()
        get_settings.cache_clear()
        settings2 = get_settings()
        assert settings1 is not settings2
