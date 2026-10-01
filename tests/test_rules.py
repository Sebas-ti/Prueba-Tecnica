import pytest

from app.agent import rules


@pytest.mark.parametrize("imp,urg,expected", [
    ("alto", "alta", "P1"), ("alto", "media", "P2"), ("medio", "alta", "P2"),
    ("alto", "baja", "P3"), ("medio", "media", "P3"), ("bajo", "alta", "P3"),
    ("medio", "baja", "P4"), ("bajo", "media", "P4"), ("bajo", "baja", "P4"),
])
def test_priority_matrix(imp, urg, expected):
    assert rules.classify_priority(impacto=imp, urgencia=urg)["prioridad"] == expected


def test_security_incident_is_raised_to_p2():
    r = rules.classify_priority(impacto="bajo", urgencia="baja", descripcion="posible vulnerabilidad de acceso")
    assert r["prioridad"] == "P2"
    assert any("4.3.a" in j for j in r["justificacion"])


def test_production_outage_is_p1():
    r = rules.classify_priority(descripcion="El sistema está caído para todos los usuarios")
    assert r["prioridad"] == "P1"


def test_regulatory_deadline_parsed_from_description():
    r = rules.classify_priority(impacto="medio", urgencia="media",
                                descripcion="Requerimiento de la Superintendencia; la fecha límite vence en 3 días hábiles")
    assert r["prioridad"] == "P1"


def test_effort_matches_guide_example():
    # Ejemplo literal de la Guía de Estimación (sección 5): 122 h, talla L
    r = rules.estimate_effort(tipo="integracion", complejidad="media", sistemas_integrados=3)
    assert r["horas_estimadas"] == 122
    assert r["talla"] == "L"


def test_effort_with_data_migration():
    r = rules.estimate_effort(tipo="migracion", complejidad="alta", sistemas_integrados=3, requiere_migracion_datos=True)
    assert r["horas_estimadas"] == 299 and r["talla"] == "XL"


def test_effort_rejects_invalid_type():
    with pytest.raises(ValueError):
        rules.estimate_effort(tipo="magia")
