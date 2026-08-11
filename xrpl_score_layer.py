"""
XRPL Score Layer — Milestone M3
==================================

Scopo (e SOLO questo):
- Combinare le feature prodotte da xrpl_feature_engine.py (M2) in due score
  0-100: XRPL Ecosystem Growth Score e XRP Capture & Dependency Score.

Questo modulo NON fa chiamate API, NON legge i RAW direttamente (solo le
feature gia' calcolate da M2), NON produce Divergence State, NON produce
Decision Engine, NON tocca Telegram/alert/Market Score/Rotation Engine/
Altseason Score esistenti. M1 e M2 non sono state modificate.

=== Normalizzazione: SOLO metodologie gia' congelate, nessuna soglia
    inventata ===

Il modello quantitativo approvato prevede quattro famiglie di
normalizzazione: percentile storico, z-score robusto (mediana/MAD), trend
vs media mobile, log-dampening. Per trasformare in modo statisticamente
onesto un valore in un "sotto-punteggio" 0-100 comparabile, senza inventare
soglie lineari arbitrarie (es. "crescita 0% = 50 punti"), qui si applica
UNA SOLA trasformazione aggiuntiva, essa stessa non arbitraria: la funzione
di ripartizione (CDF) della normale standard, Phi(z) = 0.5*(1+erf(z/sqrt(2))),
applicata pero' non al valore grezzo di trend_vs_ma() cosi' com'e', ma dopo
averlo ricalibrato correttamente. trend_vs_ma() in M2 calcola
(current - mediana) / MAD con MAD grezzo (non scalato) — questo NON e' di
per se' uno z-score standard: per una normale, MAD_teorico = Phi^-1(0.75) *
sigma (costante verificata numericamente = 0.6744897501960816, risultato
consolidato di statistica robusta, non assunta a memoria), quindi va
applicato il fattore di correzione z_std = Phi^-1(0.75) * z_raw_mad PRIMA
di passare per Phi(). Senza questa correzione Phi() sovrastimerebbe
sistematicamente l'estremita' del dato (es. z_raw=1.0 letto direttamente
darebbe l'84.1 percentile invece del 75.0 corretto).

Questa trasformazione si applica SOLO alle due metriche il cui valore
restituito da M2 e' gia', per costruzione, uno z-score robusto calcolato
con trend_vs_ma (mediana/MAD) su una finestra storica reale:
  - rwa_value_trend (M2 -> trend_vs_ma sui livelli RWA)
  - rlusd_supply_trend (M2 -> trend_vs_ma sui livelli di supply RLUSD)

Tutte le altre metriche del modello approvato richiederebbero un percentile
storico calcolato sulla SERIE dei valori gia' derivati (es. serie storica
dei tassi di crescita, non dei livelli grezzi) — dato che M2 restituisce
solo il valore piu' recente per ogni chiamata (non una serie), e che questo
modulo non puo' leggere i RAW direttamente per ricostruirla, quella
normalizzazione non e' oggi eseguibile in modo corretto. Per queste
metriche lo Score Layer non inventa un numero: le tratta come NON_MATURE
a livello di normalizzazione, anche quando M2 stesso le riporta ACTIVE.
Questo e' un gap dichiarato esplicitamente nel deliverable, non aggirato.
"""

import math
import logging
from datetime import datetime, timezone

import xrpl_feature_engine as fe

log = logging.getLogger("xrpl_score_layer")

STATUS_ACTIVE = fe.STATUS_ACTIVE
STATUS_PARTIAL = fe.STATUS_PARTIAL
STATUS_NON_MATURE = fe.STATUS_NON_MATURE
STATUS_MISSING = fe.STATUS_MISSING

NORM_ZSCORE_CDF = "zscore_cdf"       # M2 restituisce gia' uno z-score robusto: applico Phi(z)
NORM_UNAVAILABLE = "unavailable"     # richiederebbe percentile-di-storico non ricostruibile oggi

SCORE_STATUS_COMPUTED = "COMPUTED"
SCORE_STATUS_NOT_COMPUTABLE = "NOT_COMPUTABLE"

CONFIDENCE_HIGH = "HIGH"
CONFIDENCE_MEDIUM = "MEDIUM"
CONFIDENCE_LOW = "LOW"
CONFIDENCE_LOW_FORCED = "LOW_CONFIDENCE"


# ============================================================
# TRASFORMAZIONE STATISTICA (non arbitraria)
# ============================================================

def _zscore_to_percentile(z_raw_mad):
    """Converte in percentile un valore di trend_vs_ma() di M2.

    ATTENZIONE ALLA CALIBRAZIONE: trend_vs_ma() in xrpl_feature_engine.py
    calcola (current - mediana) / MAD, dove MAD e' il median absolute
    deviation GREZZO, non scalato. Questo NON e' direttamente uno z-score
    standard compatibile con la CDF della normale: per una distribuzione
    normale, MAD_teorico = Phi^-1(0.75) * sigma (con Phi^-1(0.75) verificato
    numericamente = 0.6744897501960816, non assunto a memoria), quindi
    sigma_hat = MAD_osservato / Phi^-1(0.75). Lo z-score standard e' percio':
        z_std = (current - mediana) / sigma_hat = Phi^-1(0.75) * z_raw_mad
    Senza questa correzione, Phi(z_raw_mad) sovrastima sistematicamente
    l'estremita' del dato (es. z_raw=1.0 letto direttamente darebbe l'84.1
    percentile, mentre il valore corretto e' il 75.0 percentile).
    Questa costante di consistenza MAD->sigma e' un risultato di statistica
    robusta consolidato (Iglewicz & Hoaglin), non una soglia di business."""
    if z_raw_mad is None:
        return None
    try:
        z_raw_mad = float(z_raw_mad)
    except (TypeError, ValueError):
        return None
    z_std = _MAD_TO_STANDARD_Z_FACTOR * z_raw_mad
    pct = 0.5 * (1.0 + math.erf(z_std / math.sqrt(2.0))) * 100.0
    # clip solo per sicurezza numerica in coda (z estremi), non un cutoff di business
    return max(0.0, min(100.0, pct))


# Phi^-1(0.75): percentile 75 della normale standard, verificato numericamente
# (non assunto a memoria) risolvendo Phi(z)=0.75 per bisezione sulla erf.
# E' la costante di consistenza standard per convertire un MAD grezzo nel
# suo sigma equivalente sotto ipotesi di normalita' (Iglewicz & Hoaglin).
_MAD_TO_STANDARD_Z_FACTOR = 0.6744897501960816


# ============================================================
# REGISTRI METRICHE — pesi gia' approvati, un solo posto dove sono definiti
# ============================================================
# Ogni metrica: name, weight (frazione DENTRO la categoria), feature_key
# (None se M2 non implementa ancora questa metrica come feature dedicata),
# normalization (NORM_ZSCORE_CDF o NORM_UNAVAILABLE), indispensable (bool,
# per il meccanismo di LOW_CONFIDENCE forzata).

SCORE1_CATEGORIES = {
    "A": {
        "label": "Institutional Capital Footprint",
        "macro_weight": 0.30,
        "metrics": [
            {"name": "rwa_distributed", "weight": 0.55, "feature_key": "rwa_value_trend",
             "normalization": NORM_ZSCORE_CDF, "indispensable": True},
            {"name": "rwa_growth", "weight": 0.25, "feature_key": "rwa_growth_30d",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
            {"name": "rwa_represented", "weight": 0.20, "feature_key": None,
             "normalization": None, "indispensable": False},
        ],
    },
    "B": {
        "label": "Stablecoin & Liquidity Infrastructure",
        "macro_weight": 0.25,
        "metrics": [
            {"name": "rlusd_circulating_supply", "weight": 1.00, "feature_key": "rlusd_supply_trend",
             "normalization": NORM_ZSCORE_CDF, "indispensable": True},
        ],
    },
    "C": {
        "label": "Market Structure & Trading Activity",
        "macro_weight": 0.25,
        "metrics": [
            {"name": "dex_volume", "weight": 0.60, "feature_key": "dex_volume_growth",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
            {"name": "amm_liquidity", "weight": 0.40, "feature_key": "amm_growth",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
        ],
    },
    "D": {
        "label": "Network Utility Activity",
        "macro_weight": 0.20,
        "metrics": [
            {"name": "tx_payment_activity", "weight": 0.60, "feature_key": None,
             "normalization": None, "indispensable": False},
            {"name": "trustline_growth", "weight": 0.40, "feature_key": "trustline_growth",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
        ],
    },
}

SCORE2_CATEGORIES = {
    "F": {
        "label": "XRP Economic Dependency",
        "macro_weight": 0.60,
        "metrics": [
            {"name": "pct_volume_dex_xrp", "weight": 0.40, "feature_key": "xrp_dependency_ratio",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
            {"name": "fee_burn_per_tx", "weight": 0.35, "feature_key": "fee_per_tx",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
            {"name": "xrp_rlusd_pair_growth", "weight": 0.15, "feature_key": "xrp_rlusd_pair_growth",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
            {"name": "pool_liquidity_share", "weight": 0.10, "feature_key": "xrp_pool_share",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
        ],
    },
    "E": {
        "label": "XRP Value Capture",
        "macro_weight": 0.40,
        "metrics": [
            {"name": "xrp_btc_relative_strength", "weight": 0.60, "feature_key": "xrp_btc_relative_strength",
             "normalization": NORM_UNAVAILABLE, "indispensable": True},
            {"name": "xrp_eth_relative_strength", "weight": 0.40, "feature_key": "xrp_eth_relative_strength",
             "normalization": NORM_UNAVAILABLE, "indispensable": False},
        ],
    },
}


# ============================================================
# CALCOLO PER CATEGORIA
# ============================================================

def _resolve_metric(metric, features):
    """Ritorna (status_effettivo, sub_score_0_100_o_None, reason).
    status_effettivo e' sempre uno tra ACTIVE/PARTIAL/NON_MATURE/MISSING,
    anche quando diverge dallo status che M2 riporta per la stessa feature
    (succede quando M2 dice ACTIVE ma la normalizzazione richiesta da
    questo score non e' ancora ricostruibile: qui diventa NON_MATURE)."""
    feature_key = metric["feature_key"]
    if feature_key is None:
        return STATUS_MISSING, None, "metrica non ancora implementata come feature dedicata in M2"

    feat = features.get(feature_key)
    if feat is None:
        return STATUS_MISSING, None, f"feature '{feature_key}' non presente nell'output di M2"

    m2_status = feat.get("status")
    m2_reason = feat.get("reason")

    if m2_status == STATUS_MISSING:
        return STATUS_MISSING, None, m2_reason or "MISSING in M2, nessun motivo riportato"
    if m2_status == STATUS_NON_MATURE:
        return STATUS_NON_MATURE, None, m2_reason or "NON_MATURE in M2, nessun motivo riportato"

    # Qui m2_status e' ACTIVE o PARTIAL: il dato grezzo di M2 esiste.
    # Ma la normalizzazione richiesta da QUESTO score potrebbe non essere
    # ancora ricostruibile — controllo separato, non lo stesso di M2.
    if metric["normalization"] == NORM_ZSCORE_CDF:
        sub_score = _zscore_to_percentile(feat.get("value"))
        if sub_score is None:
            return STATUS_NON_MATURE, None, (
                "valore non numerico o assente nonostante lo status M2 attivo: "
                "normalizzazione z-score->percentile non applicabile"
            )
        return m2_status, sub_score, None

    # NORM_UNAVAILABLE: anche con dato M2 attivo, la normalizzazione
    # approvata per questa metrica richiede un percentile storico sulla
    # serie dei valori derivati (non sui livelli grezzi), che M2 non
    # espone come serie e che questo modulo non puo' ricostruire perche'
    # non ha accesso diretto ai RAW. Dichiarato NON_MATURE, non aggirato.
    return STATUS_NON_MATURE, None, (
        f"dato M2 disponibile (status {m2_status}) ma la normalizzazione approvata per "
        f"questa metrica richiede un percentile storico sulla serie dei valori derivati, "
        f"non ancora ricostruibile: M2 espone solo il valore corrente, non una serie "
        f"storica, e lo Score Layer non ha accesso diretto ai RAW per costruirla"
    )


def _compute_category(category_key, category_def, features):
    metrics = category_def["metrics"]
    nominal_weight_sum = sum(m["weight"] for m in metrics)

    active_metrics, partial_metrics, non_mature_metrics, missing_metrics = [], [], [], []
    points = 0.0
    available_weight = 0.0
    partial_weight = 0.0
    reasons = []

    for m in metrics:
        status, sub_score, reason = _resolve_metric(m, features)
        qualified_name = f"{category_key}.{m['name']}"
        if reason:
            reasons.append(f"{qualified_name}: {reason}")

        if status == STATUS_MISSING:
            missing_metrics.append(qualified_name)
            continue
        if status == STATUS_NON_MATURE:
            non_mature_metrics.append(qualified_name)
            continue

        multiplier = 1.0 if status == STATUS_ACTIVE else 0.5  # PARTIAL = 50% peso
        w = m["weight"] * multiplier
        available_weight += w
        if status == STATUS_PARTIAL:
            partial_weight += w
        points += w * (sub_score / 100.0)
        (active_metrics if status == STATUS_ACTIVE else partial_metrics).append(qualified_name)

    coverage_ratio = (available_weight / nominal_weight_sum) if nominal_weight_sum > 0 else 0.0

    if available_weight <= 0:
        return {
            "category": category_key,
            "label": category_def["label"],
            "score": None,
            "status": SCORE_STATUS_NOT_COMPUTABLE,
            "macro_weight": category_def["macro_weight"],
            "nominal_weight": nominal_weight_sum,
            "available_weight": available_weight,
            "partial_weight": partial_weight,
            "coverage_ratio": coverage_ratio,
            "active_metrics": active_metrics,
            "partial_metrics": partial_metrics,
            "non_mature_metrics": non_mature_metrics,
            "missing_metrics": missing_metrics,
            "reasons": reasons,
        }

    score = points / available_weight * 100.0
    return {
        "category": category_key,
        "label": category_def["label"],
        "score": score,
        "status": SCORE_STATUS_COMPUTED,
        "macro_weight": category_def["macro_weight"],
        "nominal_weight": nominal_weight_sum,
        "available_weight": available_weight,
        "partial_weight": partial_weight,
        "coverage_ratio": coverage_ratio,
        "active_metrics": active_metrics,
        "partial_metrics": partial_metrics,
        "non_mature_metrics": non_mature_metrics,
        "missing_metrics": missing_metrics,
        "reasons": reasons,
    }


# ============================================================
# CONFIDENCE (separata dallo score)
# ============================================================

def _compute_confidence(category_results, categories_def, features, indispensable_feature_keys):
    macro_total = sum(c["macro_weight"] for c in categories_def.values())

    coverage_num = sum(
        categories_def[k]["macro_weight"] * category_results[k]["coverage_ratio"]
        for k in categories_def
    )
    coverage_score = (coverage_num / macro_total * 100.0) if macro_total > 0 else 0.0

    maturity_num = 0.0
    maturity_den = 0.0
    for k in categories_def:
        cr = category_results[k]
        n_active = len(cr["active_metrics"])
        n_partial = len(cr["partial_metrics"])
        n_avail = n_active + n_partial
        if n_avail > 0:
            w = categories_def[k]["macro_weight"]
            maturity_den += w
            maturity_num += w * (n_active / n_avail * 100.0)
    maturity_score = (maturity_num / maturity_den) if maturity_den > 0 else 0.0

    now = datetime.now(timezone.utc)
    ages_hours = []
    for feat in features.values():
        if feat.get("status") in (STATUS_ACTIVE, STATUS_PARTIAL) and feat.get("as_of"):
            dt = fe._parse_ts(feat["as_of"])
            if dt is not None:
                ages_hours.append((now - dt).total_seconds() / 3600.0)
    if ages_hours:
        avg_age_hours = sum(ages_hours) / len(ages_hours)
        # decadimento lineare: fresco (<=24h) ~100, degrada a 0 attorno ai 30gg
        freshness_score = max(0.0, min(100.0, 100.0 - (avg_age_hours / 720.0 * 100.0)))
    else:
        freshness_score = 0.0

    # Cross-source agreement: nessun confronto incrociato e' oggi esposto
    # da M2 come output della Score Layer puo' leggere (le fonti di
    # cross-check, es. DeFiLlama, sono raccolte in M1 ma non confrontate
    # in un output dedicato) -> componente non disponibile, esclusa dalla
    # media invece di essere inventata.
    # La confidence NON deve mai sembrare alta solo perche' la poca
    # copertura disponibile e' di buona qualita': coverage_score agisce
    # da fattore moltiplicativo, non da componente paritaria nella media.
    # Stessa logica anti-inflazione gia' richiesta a livello di categoria,
    # qui applicata in modo coerente anche al valore aggregato.
    quality_components = [v for v in (maturity_score, freshness_score) if v is not None]
    quality_score = sum(quality_components) / len(quality_components) if quality_components else 0.0
    confidence_value = coverage_score / 100.0 * quality_score
    components = {"coverage": coverage_score, "maturity": maturity_score,
                   "freshness": freshness_score, "cross_source_agreement": None}

    indispensable_missing = []
    for fk in indispensable_feature_keys:
        feat = features.get(fk)
        if feat is None or feat.get("status") in (STATUS_NON_MATURE, STATUS_MISSING):
            indispensable_missing.append(fk)

    forced_low = False
    if indispensable_feature_keys:
        forced_low = (len(indispensable_missing) / len(indispensable_feature_keys)) > 0.5

    if forced_low:
        label = CONFIDENCE_LOW_FORCED
    elif confidence_value >= 70:
        label = CONFIDENCE_HIGH
    elif confidence_value >= 40:
        label = CONFIDENCE_MEDIUM
    else:
        label = CONFIDENCE_LOW

    return {
        "confidence_score": confidence_value,
        "confidence_label": label,
        "components": components,
        "indispensable_missing": indispensable_missing,
        "forced_low_confidence": forced_low,
    }


# ============================================================
# ORCHESTRAZIONE — un punteggio
# ============================================================

def _compute_score(score_name, categories_def, features):
    category_results = {k: _compute_category(k, v, features) for k, v in categories_def.items()}

    computable = {k: cr for k, cr in category_results.items() if cr["status"] == SCORE_STATUS_COMPUTED}
    macro_available = sum(categories_def[k]["macro_weight"] for k in computable)

    active_metrics, partial_metrics, non_mature_metrics, missing_metrics = [], [], [], []
    reasons = []
    for k, cr in category_results.items():
        active_metrics.extend(cr["active_metrics"])
        partial_metrics.extend(cr["partial_metrics"])
        non_mature_metrics.extend(cr["non_mature_metrics"])
        missing_metrics.extend(cr["missing_metrics"])
        reasons.extend(cr["reasons"])
        if cr["status"] == SCORE_STATUS_NOT_COMPUTABLE:
            reasons.append(f"{k} ({cr['label']}): categoria non calcolabile, nessun dato disponibile")

    indispensable_feature_keys = [
        m["feature_key"]
        for cat in categories_def.values()
        for m in cat["metrics"]
        if m.get("indispensable") and m["feature_key"] is not None
    ]
    confidence = _compute_confidence(category_results, categories_def, features, indispensable_feature_keys)

    # pesi nominali totali per lo score (in % del punteggio complessivo)
    active_weight_nom = 0.0
    partial_weight_nom = 0.0
    missing_weight_nom = 0.0
    for k, cat in categories_def.items():
        for m in cat["metrics"]:
            nominal = cat["macro_weight"] * m["weight"]
            qualified_name = f"{k}.{m['name']}"
            if qualified_name in active_metrics:
                active_weight_nom += nominal
            elif qualified_name in partial_metrics:
                partial_weight_nom += nominal
            else:
                missing_weight_nom += nominal  # NON_MATURE + MISSING uniti, come richiesto

    if macro_available <= 0:
        score_value = None
        status = SCORE_STATUS_NOT_COMPUTABLE
    else:
        weighted_sum = sum(computable[k]["score"] * categories_def[k]["macro_weight"] for k in computable)
        score_value = weighted_sum / macro_available
        status = SCORE_STATUS_COMPUTED

    reasons.insert(0, (
        "Normalizzazione: solo z-score robusto (M2, mediana/MAD) convertito in percentile "
        "via CDF normale per le metriche che M2 espone gia' come z-score (rwa_value_trend, "
        "rlusd_supply_trend). Tutte le altre metriche richiederebbero un percentile storico "
        "sulla serie dei valori derivati, non ricostruibile da questo modulo (M2 espone solo "
        "il valore corrente, e questo modulo non legge i RAW direttamente): restano NON_MATURE "
        "anche quando M2 le riporta ACTIVE."
    ))

    return {
        "score_name": score_name,
        "score": score_value,
        "status": status,
        "confidence": confidence,
        "available_weight": active_weight_nom + partial_weight_nom,
        "missing_weight": missing_weight_nom,
        "partial_weight": partial_weight_nom,
        "active_metrics": active_metrics,
        "partial_metrics": partial_metrics,
        "non_mature_metrics": non_mature_metrics,
        "missing_metrics": missing_metrics,
        "category_breakdown": category_results,
        "reasons": reasons,
    }


def compute_ecosystem_growth_score(rot_get_history_func=None, rot_perf_func=None, features=None):
    """XRPL Ecosystem Growth Score (categorie A+B+C+D).
    'features' e' un parametro di test: se assente, chiama
    xrpl_feature_engine.compute_all_features() (comportamento reale)."""
    if features is None:
        features = fe.compute_all_features(rot_get_history_func, rot_perf_func)
    return _compute_score("XRPL Ecosystem Growth Score", SCORE1_CATEGORIES, features)


def compute_capture_dependency_score(rot_get_history_func=None, rot_perf_func=None, features=None):
    """XRP Capture & Dependency Score (categorie F+E).
    'features' e' un parametro di test: se assente, chiama
    xrpl_feature_engine.compute_all_features() (comportamento reale)."""
    if features is None:
        features = fe.compute_all_features(rot_get_history_func, rot_perf_func)
    return _compute_score("XRP Capture & Dependency Score", SCORE2_CATEGORIES, features)


if __name__ == "__main__":
    import json
    result = {
        "ecosystem_growth": compute_ecosystem_growth_score(),
        "capture_dependency": compute_capture_dependency_score(),
    }
    print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
