import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


DISCLAIMER = "This is not a medical diagnosis tool."


def _normalize_text(text: str) -> str:
    text = text.strip().lower()
    # Keep letters/numbers/spaces only.
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text


def _extract_simple_keywords(text: str) -> List[str]:
    """
    Very small tokenizer: splits on spaces and keeps short "signals" too.
    This is intentionally simple and rule-based.
    """
    text = _normalize_text(text)
    tokens = [t for t in text.split(" ") if t]
    # De-duplicate while preserving order
    seen = set()
    out = []
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def _matched_aliases(record: "DiseaseRecord", query: str) -> List[str]:
    """
    Finds aliases where the alias string appears inside the query.
    Used to detect whether the user likely entered a disease name.
    """
    q = _normalize_text(query)
    matched: List[str] = []
    for alias in record.aliases:
        a = _normalize_text(alias)
        if a and a in q:
            matched.append(alias)
    # De-duplicate while preserving order
    return list(dict.fromkeys(matched))


@dataclass
class DiseaseRecord:
    name: str
    aliases: List[str]
    symptoms: List[str]
    description: str
    precautions: List[str]
    otc_medicines: List[Dict[str, Any]]
    dosage_guidelines: List[str]
    when_to_consult_doctor: List[str]


class DiseaseMatcher:
    def __init__(self, dataset: List[Dict[str, Any]]):
        self.records: List[DiseaseRecord] = []
        for item in dataset:
            self.records.append(
                DiseaseRecord(
                    name=item["name"],
                    aliases=item.get("aliases", []),
                    symptoms=item.get("symptoms", []),
                    description=item.get("description", ""),
                    precautions=item.get("precautions", []),
                    otc_medicines=item.get("otc_medicines", []),
                    dosage_guidelines=item.get("dosage_guidelines", []),
                    when_to_consult_doctor=item.get("when_to_consult_doctor", []),
                )
            )

    @staticmethod
    def _score_for_record(record: DiseaseRecord, query: str, query_tokens: List[str]) -> Tuple[float, List[str]]:
        """
        Returns (score, matched_keywords).
        Score is based on:
        - alias substring matches (+2)
        - symptom keyword matches (+1)
        - light token overlap (small fractional boost)
        """
        q = _normalize_text(query)
        matched = []
        score = 0.0

        # Aliases: substring matches get a higher weight.
        for alias in record.aliases:
            a = _normalize_text(alias)
            if not a:
                continue
            if a in q:
                score += 2.0
                matched.append(alias)

        # Symptoms: keyword/phrase match.
        for sym in record.symptoms:
            s = _normalize_text(sym)
            if not s:
                continue
            if s in q:
                score += 1.0
                matched.append(sym)
            else:
                # If symptom is a single word, allow token overlap.
                if " " not in s and s in query_tokens:
                    score += 0.5
                    matched.append(sym)

        # Small boost for overlap with any symptom words.
        symptom_words = set()
        for sym in record.symptoms:
            symptom_words.update(_extract_simple_keywords(sym))
        if symptom_words:
            overlap = sum(1 for t in query_tokens if t in symptom_words)
            score += 0.15 * (overlap / max(len(symptom_words), 1))

        return score, list(dict.fromkeys(matched))

    def predict(self, query: str, top_k: int = 3, min_confidence: float = 0.18) -> Dict[str, Any]:
        """
        Returns a JSON-serializable response for the API.
        """
        query = (query or "").strip()
        if not query:
            return {
                "query": query,
                "results": [],
                "message": "Please enter your symptoms or a disease name.",
                "disclaimer": DISCLAIMER,
            }

        query_tokens = _extract_simple_keywords(query)

        scored: List[Tuple[float, DiseaseRecord, List[str]]] = []
        for record in self.records:
            score, matched = self._score_for_record(record, query, query_tokens)
            scored.append((score, record, matched))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score = scored[0][0] if scored else 0.0

        results: List[Dict[str, Any]] = []
        for score, record, matched in scored[: max(top_k, 1)]:
            # Confidence normalization (rough heuristic).
            denom = float(max(len(record.symptoms) + len(record.aliases) + 1, 1))
            confidence = min(1.0, score / denom)
            if best_score > 0:
                # Convert to relative confidence as well.
                confidence = max(confidence, (score / best_score) * 0.6)

            results.append(
                {
                    "name": record.name,
                    "confidence": round(confidence, 2),
                    "matched_signals": matched[:10],
                    "description": record.description,
                    "precautions": record.precautions,
                    "otc_medicines": record.otc_medicines,
                    "dosage_guidelines": record.dosage_guidelines,
                    "when_to_consult_doctor": record.when_to_consult_doctor,
                }
            )

        best_conf = results[0]["confidence"] if results else 0.0
        if not results or best_conf < min_confidence:
            return {
                "query": query,
                "results": results,
                "message": "I couldn't find a confident match from the limited rule set. Still review the general guidance below and consider medical evaluation if symptoms are concerning.",
                "disclaimer": DISCLAIMER,
                "mode": "general",
            }

        # If user appears to have typed a disease name (not just symptom phrases),
        # show medicine-only output (still not diagnosis).
        best_record = results[0]["name"]
        matched_best = [r for s, r, m in scored if r.name == best_record]
        # matched_best will contain exactly one item; keep safe anyway
        best_disease_record = matched_best[0] if matched_best else scored[0][1]

        alias_hits = _matched_aliases(best_disease_record, query)
        looks_like_disease_name = alias_hits and len(query_tokens) <= 4

        if looks_like_disease_name:
            meds = results[0]["otc_medicines"] or []
            return {
                "query": query,
                "mode": "medicine_only",
                "message": f"Possible condition: {results[0]['name']} (not a diagnosis).",
                "disclaimer": DISCLAIMER,
                "medicine_types": len(meds),
                "medicines": meds,
                "when_to_consult_doctor": results[0]["when_to_consult_doctor"],
            }

        return {
            "query": query,
            "mode": "general",
            "results": results,
            "message": "Possible matches (not a diagnosis).",
            "disclaimer": DISCLAIMER,
        }


def load_dataset(dataset_path: Path) -> List[Dict[str, Any]]:
    with dataset_path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "diseases" not in data:
        raise ValueError("Dataset JSON must be an object with a 'diseases' key.")
    return data["diseases"]


def build_matcher(dataset_path: Path) -> DiseaseMatcher:
    dataset = load_dataset(dataset_path)
    return DiseaseMatcher(dataset)


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"

