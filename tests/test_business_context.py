"""
Tests for BusinessContext model and ERP hint pack loading.
Refs: VAL-128
"""
import json
import pytest
from dataclasses import asdict

from shared.memory.client_profile import (
    BusinessContext,
    ClientProfile,
)


# ── BusinessContext model ────────────────────────────────────────────────────


class TestBusinessContextModel:
    """Test BusinessContext creation, defaults, and serialization."""

    def test_create_full(self):
        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            industry="distribucion_insumos_impresion",
            country="AR",
            city="Rio Cuarto, Cordoba",
            erp_type="gestion_pyme_argentina",
            expected_entities=["articulos", "stock", "ventas", "clientes"],
            notes="SQL Server, ~50 tables, uses Tango-like schema",
        )
        assert ctx.company_name == "SYSCOP SRL"
        assert ctx.country == "AR"
        assert "articulos" in ctx.expected_entities
        assert len(ctx.expected_entities) == 4

    def test_create_minimal(self):
        ctx = BusinessContext()
        assert ctx.company_name == ""
        assert ctx.country == ""
        assert ctx.expected_entities == []
        assert ctx.notes == ""

    def test_serialization_roundtrip(self):
        ctx = BusinessContext(
            company_name="Test SRL",
            industry="retail",
            country="AR",
            expected_entities=["ventas", "stock"],
        )
        d = asdict(ctx)
        assert isinstance(d, dict)
        assert d["company_name"] == "Test SRL"
        assert d["expected_entities"] == ["ventas", "stock"]
        # Roundtrip
        ctx2 = BusinessContext(**d)
        assert ctx2.company_name == ctx.company_name
        assert ctx2.expected_entities == ctx.expected_entities

    def test_json_roundtrip(self):
        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            industry="distribucion",
            country="AR",
            city="Rio Cuarto",
            erp_type="gestion",
            expected_entities=["ventas"],
        )
        j = json.dumps(asdict(ctx))
        d = json.loads(j)
        ctx2 = BusinessContext(**d)
        assert ctx2.company_name == "SYSCOP SRL"


# ── ClientProfile with business_context ──────────────────────────────────────


class TestClientProfileWithBusinessContext:
    """Test ClientProfile integration with BusinessContext."""

    def test_profile_without_business_context(self):
        """Backward compat: profile works without business_context."""
        profile = ClientProfile.new("test_client")
        assert profile.business_context is None
        d = profile.to_dict()
        assert d["business_context"] is None

    def test_profile_with_business_context(self):
        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            industry="distribucion",
            country="AR",
        )
        profile = ClientProfile.new("syscop")
        profile.business_context = ctx
        assert profile.business_context.company_name == "SYSCOP SRL"

    def test_profile_to_dict_with_context(self):
        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            country="AR",
            expected_entities=["ventas", "stock"],
        )
        profile = ClientProfile.new("syscop")
        profile.business_context = ctx
        d = profile.to_dict()
        assert isinstance(d["business_context"], dict)
        assert d["business_context"]["company_name"] == "SYSCOP SRL"
        assert d["business_context"]["expected_entities"] == ["ventas", "stock"]

    def test_profile_serialization_roundtrip(self):
        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            industry="distribucion",
            country="AR",
            city="Rio Cuarto",
            erp_type="gestion",
            expected_entities=["articulos", "ventas"],
            notes="Tango-like schema",
        )
        profile = ClientProfile.new("syscop")
        profile.business_context = ctx

        d = profile.to_dict()
        profile2 = ClientProfile.from_dict(d)

        assert profile2.business_context is not None
        assert profile2.business_context.company_name == "SYSCOP SRL"
        assert profile2.business_context.country == "AR"
        assert profile2.business_context.expected_entities == ["articulos", "ventas"]
        assert profile2.business_context.notes == "Tango-like schema"

    def test_profile_from_dict_without_context(self):
        """Old-format dicts without business_context still work."""
        d = {
            "client_name": "old_client",
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        }
        profile = ClientProfile.from_dict(d)
        assert profile.business_context is None


# ── ERP Hint Pack Loading ────────────────────────────────────────────────────


class TestERPHintPackLoading:
    """Test hint pack loader."""

    def test_load_argentina_gestion(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("argentina", "gestion")
        assert isinstance(pack, dict)
        assert "naming_conventions" in pack
        assert "table_patterns" in pack
        assert "fiscal_patterns" in pack
        assert "column_hints" in pack
        assert "business_flows" in pack

    def test_argentina_gestion_naming_conventions(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("argentina", "gestion")
        naming = pack["naming_conventions"]
        assert "Cod" in naming["id_prefixes"]
        assert "Nro" in naming["id_prefixes"]
        assert "FechaAlta" in naming["date_patterns"]

    def test_argentina_gestion_fiscal_patterns(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("argentina", "gestion")
        fiscal = pack["fiscal_patterns"]
        assert "cuit" in fiscal
        assert "CUIT" in fiscal["cuit"]["columns"]
        assert "condicion_iva" in fiscal
        assert "RI" in fiscal["condicion_iva"]["values"]

    def test_argentina_gestion_business_flows(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("argentina", "gestion")
        flows = pack["business_flows"]
        assert "distribucion" in flows
        assert "retail" in flows
        assert len(flows["distribucion"]["flow"]) > 0

    def test_fallback_unknown_country(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("narnia", "magic_erp")
        assert pack == {}

    def test_fallback_empty_strings(self):
        from core.valinor.discovery.erp_hints import load_hint_pack

        pack = load_hint_pack("", "")
        assert pack == {}


# ── Context Injection ────────────────────────────────────────────────────────


class TestContextInjection:
    """Test that business context produces valid prompt sections."""

    def test_format_with_full_context(self):
        from core.valinor.agents.cartographer import _format_business_context

        ctx = BusinessContext(
            company_name="SYSCOP SRL",
            industry="distribucion_insumos_impresion",
            country="AR",
            city="Rio Cuarto, Cordoba",
            erp_type="gestion_pyme_argentina",
            expected_entities=["articulos", "stock", "ventas"],
            notes="SQL Server database",
        )
        from core.valinor.discovery.erp_hints import load_hint_pack
        hint_pack = load_hint_pack("argentina", "gestion")

        result = _format_business_context(ctx, hint_pack)

        assert "## Business Context" in result
        assert "SYSCOP SRL" in result
        assert "Rio Cuarto, Cordoba" in result
        assert "distribucion_insumos_impresion" in result
        assert "articulos, stock, ventas" in result
        assert "SQL Server database" in result
        assert "## ERP Naming Conventions" in result
        assert "Cod" in result
        assert "Fiscal Patterns" in result

    def test_format_without_context(self):
        from core.valinor.agents.cartographer import _format_business_context

        result = _format_business_context(None, {})
        assert result == ""

    def test_format_without_hint_pack(self):
        from core.valinor.agents.cartographer import _format_business_context

        ctx = BusinessContext(
            company_name="Test Company",
            industry="retail",
            country="XX",
        )
        result = _format_business_context(ctx, {})

        assert "## Business Context" in result
        assert "Test Company" in result
        assert "ERP Naming Conventions" not in result

    def test_format_minimal_context(self):
        from core.valinor.agents.cartographer import _format_business_context

        ctx = BusinessContext(company_name="MinCo")
        result = _format_business_context(ctx, {})

        assert "## Business Context" in result
        assert "MinCo" in result
