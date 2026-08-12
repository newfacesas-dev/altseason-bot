"""
XRPL Confidence Engine — Milestone M4 (parte 1/2)
=====================================================

Scopo (e SOLO questo): calcolare la confidence finale di un risultato
prodotto da xrpl_score_layer.py, usando esclusivamente i quattro fattori
gia' approvati: coverage, freshness, maturita' storica, cross-source
agreement (solo dove realmente disponibile). Non tocca M1/M2/M3, non fa
chiamate API, non legge i RAW direttamente.

Formula (stesso principio anti-inflazione gia' corretto in M3, riusato
qui, non reinventato): la confidence e' MOLTIPLICATIVA rispetto alla
copertura, non una media semplice — una qualita' alta calcolata su
pochissimi dati disponibili non deve MAI risultare in una confidence alta:

    quality = media(maturity, freshness)  [solo componenti disponibili]
    confidence_score = coverage/100 * quality

Cross-source disagreement agisce da TETTO (cap), mai mediato dentro la
formula: se le fonti sono in disaccordo, la confidence viene abbassata
forzatamente sotto la soglia MEDIUM/LOW gia' definita (39, appena sotto
la soglia 40 che separa MEDIUM da LOW nelle etichette sottostanti — non
un nuovo numero arbitrario, e' ancorato alle soglie di etichetta gia'
in uso). Se il cross-check non e' disponibile, lo stato e' NOT_AVAILABLE
e la componente viene esclusa, mai inventata.
"""

import logging
from datetime import datetime, timezone

import xrpl_feature_engine as fe
import xrpl_score_layer as sl

log = logging.getLogger("xrpl_confidence_engine")

LABEL_HIGH = "HIGH"
LABEL_MEDIUM = "MEDIUM"
LABEL_LOW = "LOW"
LABEL_NOT_MATURE = "NOT_MATURE"

CROSS_SOURCE_AGREE = "AGREE"
CROSS_SOURCE_DISAGREE = "DISAGREE"
CROSS_SOURCE_NOT_AVAILABLE = "NOT_AVAILABLE"

_DISAGREEMENT_CAP = 39.0  # ancorato alla soglia label MEDIUM/LOW=40 sotto, non un nuovo numero arbitrario
_FRESHNESS_ZERO_HOURS = 720.0  # 30gg: stesso valore gia' usato in xrpl_score_layer.py (M3), riusato qui per coerenza
_CONFIDENCE_HIGH_THRESHOLD = 70.0    # stesso valore gia' usato in xrpl_score_layer.py (M3), non un nuovo numero
_CONFIDENCE_MEDIUM_THRESHOLD = 40.0  # idem


def _resolve_cross_source_status(cross_source_checks):
    """cross_source_checks: None, o lista di dict {'metric':.., 'agree': bool}.
    Nessuna invenzione: se non forniti controlli, lo stato e' esplicitamente
    NOT_AVAILABLE, mai AGREE per default."""
    if not cross_source_checks:
        return CROSS_SOURCE_NOT_AVAILABLE
    disagreements = [c for c in cross_source_checks if c.get("agree") is False]
    if disagreements:
        return CROSS_SOURCE_DISAGREE
    agreements = [c for c in cross_source_checks if c.get("agree") is True]
    if agreements:
        return CROSS_SOURCE_AGREE
    return CROSS_SOURCE_NOT_AVAILABLE


def _score_registry_for(score_result):
    """Determina quale registro (SCORE1/SCORE2) usare in base alle categorie
    presenti nel breakdown, per poter risalire da nome-metrica qualificato
    a feature_key (serve per la freschezza, che vive solo in M2)."""
    keys = set(score_result.get("category_breakdown", {}).keys())
    if keys == {"A", "B", "C", "D"}:
        return sl.SCORE1_CATEGORIES
    if keys == {"F", "E"}:
        return sl.SCORE2_CATEGORIES
    return {}


def _compute_coverage(category_breakdown):
    macro_total = sum(c["macro_weight"] for c in category_breakdown.values())
    if macro_total <= 0:
        return 0.0
    num = sum(c["macro_weight"] * c["coverage_ratio"] for c in category_breakdown.values())
    return num / macro_total * 100.0


def _compute_maturity(category_breakdown):
    num, den = 0.0, 0.0
    for c in category_breakdown.values():
        n_active = len(c["active_metrics"])
        n_partial = len(c["partial_metrics"])
        n_avail = n_active + n_partial
        if n_avail > 0:
            den += c["macro_weight"]
            num += c["macro_weight"] * (n_active / n_avail * 100.0)
    return (num / den) if den > 0 else None


def _compute_freshness(score_result, features):
    registry = _score_registry_for(score_result)
    if not registry:
        return None
    active_and_partial = set()
    for c in score_result["category_breakdown"].values():
        active_and_partial.update(c["active_metrics"])
        active_and_partial.update(c["partial_metrics"])
    now = datetime.now(timezone.utc)
    ages_hours = []
    for cat_key, cat_def in registry.items():
        for m in cat_def["metrics"]:
            qualified = f"{cat_key}.{m['name']}"
            if qualified not in active_and_partial or not m.get("feature_key"):
                continue
            feat = features.get(m["feature_key"])
            if not feat or not feat.get("as_of"):
                continue
            dt = fe._parse_ts(feat["as_of"])
            if dt is not None:
                ages_hours.append((now - dt).total_seconds() / 3600.0)
    if not ages_hours:
        return None
    avg_age_hours = sum(ages_hours) / len(ages_hours)
    return max(0.0, min(100.0, 100.0 - (avg_age_hours / _FRESHNESS_ZERO_HOURS * 100.0)))


def compute_confidence(score_result, features=None, cross_source_checks=None):
    """Calcola la confidence finale per un risultato di xrpl_score_layer.py.

    'features': se assente, chiama xrpl_feature_engine.compute_all_features()
    (comportamento reale). Parametro esposto per testabilita'.
    'cross_source_checks': lista opzionale di {'metric':.., 'agree': bool};
    se assente, cross_source_status = NOT_AVAILABLE, mai inventato."""
    if features is None:
        features = fe.compute_all_features()

    cross_source_status = _resolve_cross_source_status(cross_source_checks)
    reasons = []

    if score_result.get("status") != sl.SCORE_STATUS_COMPUTED or score_result.get("score") is None:
        reasons.append(
            "lo score sottostante non e' calcolabile (nessun dato disponibile con peso "
            "sufficiente): la confidence non ha nulla da valutare, stato NOT_MATURE per definizione"
        )
        return {
            "confidence_score": None,
            "confidence_label": LABEL_NOT_MATURE,
            "coverage": 0.0,
            "freshness": None,
            "maturity": None,
            "cross_source_status": cross_source_status,
            "reasons": reasons,
        }

    category_breakdown = score_result["category_breakdown"]
    coverage = _compute_coverage(category_breakdown)
    maturity = _compute_maturity(category_breakdown)
    freshness = _compute_freshness(score_result, features)

    quality_components = [v for v in (maturity, freshness) if v is not None]
    if maturity is None:
        reasons.append("maturity non disponibile: nessuna categoria ha metriche ACTIVE/PARTIAL")
    if freshness is None:
        reasons.append("freshness non disponibile: nessun timestamp 'as_of' utilizzabile tra le metriche attive")
    quality = sum(quality_components) / len(quality_components) if quality_components else 0.0

    confidence_score = coverage / 100.0 * quality
    reasons.append(
        f"confidence = coverage({coverage:.1f}) / 100 * media(maturity, freshness) "
        f"disponibili({quality:.1f}) — formula moltiplicativa, non media semplice, per non "
        "far sembrare affidabile un punteggio con copertura bassa"
    )

    capped = False
    if cross_source_status == CROSS_SOURCE_DISAGREE:
        if confidence_score > _DISAGREEMENT_CAP:
            capped = True
        confidence_score = min(confidence_score, _DISAGREEMENT_CAP)
        reasons.append(
            f"cross-source disagreement rilevato: confidence limitata a un tetto di "
            f"{_DISAGREEMENT_CAP} (non mediata silenziosamente con le altre componenti)"
        )

    if confidence_score >= _CONFIDENCE_HIGH_THRESHOLD:
        label = LABEL_HIGH
    elif confidence_score >= _CONFIDENCE_MEDIUM_THRESHOLD:
        label = LABEL_MEDIUM
    else:
        label = LABEL_LOW

    if capped and label != LABEL_LOW:
        # non dovrebbe accadere dato il valore del cap, ma per sicurezza
        # esplicita: il disaccordo tra fonti non deve mai risultare HIGH/MEDIUM
        label = LABEL_LOW

    return {
        "confidence_score": confidence_score,
        "confidence_label": label,
        "coverage": coverage,
        "freshness": freshness,
        "maturity": maturity,
        "cross_source_status": cross_source_status,
        "reasons": reasons,
    }
