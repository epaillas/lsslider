from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

LOGGER = logging.getLogger(__name__)

Z = 0.5
TRACER = "LRG"
ELLS = (0, 2, 4)
KMIN = 0.01
KMAX = 0.2
DK = 0.005
K_GRID = np.arange(KMIN, KMAX + 0.5 * DK, DK)

DEFAULT_MODEL = "folpsv2"
DEFAULT_BACKEND = "direct"
VISIBLE_CATEGORIES = ("cosmology", "bias", "counterterms", "stochastic_fog")
CATEGORY_LABELS = {
    "cosmology": "Cosmology",
    "bias": "Bias",
    "counterterms": "Counterterms",
    "stochastic_fog": "Stochastic / FoG",
}
CATEGORY_ORDER = {
    "cosmology": 0,
    "bias": 1,
    "counterterms": 2,
    "stochastic_fog": 3,
}
PLOT_RANGE_FRACTIONS = {
    "cosmology": 0.6,
    "bias": 0.3,
    "counterterms": 0.25,
    "stochastic_fog": 0.35,
}
PARAM_LABELS = {
    "h": "h",
    "omega_cdm": "omega_cdm",
    "omega_b": "omega_b",
    "logA": "logA",
    "n_s": "n_s",
    "w0_fld": "w0",
    "wa_fld": "wa",
    "Omega_k": "Omega_k",
    "b1p": "b1p",
    "b2p": "b2p",
    "bsp": "bsp",
    "b3p": "b3p",
    "alpha0p": "alpha0p",
    "alpha2p": "alpha2p",
    "alpha4p": "alpha4p",
    "alpha6p": "alpha6p",
    "ctp": "ctp",
    "sn0p": "sn0p",
    "sn2p": "sn2p",
    "sn4p": "sn4p",
    "X_FoG_pp": "X_FoG_pp",
}
COSMOLOGY_NAMES = {"h", "omega_cdm", "omega_b", "logA", "n_s", "w0_fld", "wa_fld", "Omega_k"}


def _configure_environment(cache_root: Path) -> None:
    mpl_cache = cache_root / "matplotlib"
    mpl_cache.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", str(mpl_cache))


def _prior_to_dict(prior: Any) -> dict[str, Any] | None:
    if prior is None:
        return None
    attrs = {}
    try:
        attrs = dict(prior.attrs)
    except Exception:
        attrs = {}
    limits = attrs.get("limits")
    if limits is not None:
        limits = list(limits)
    result = {"dist": getattr(prior, "dist", None), **attrs}
    if limits is not None:
        result["limits"] = limits
    return result


def _ref_to_dict(ref: Any) -> dict[str, Any] | None:
    if ref is None:
        return None
    try:
        attrs = dict(ref.attrs)
    except Exception:
        attrs = {}
    return {"dist": getattr(ref, "dist", None), **attrs}


def _finite_pair(values: list[Any] | tuple[Any, Any] | None) -> tuple[float, float] | None:
    if not values or len(values) != 2:
        return None
    low, high = values
    if low is None or high is None:
        return None
    if not np.isfinite(low) or not np.isfinite(high):
        return None
    return float(low), float(high)


def _categorize_param(name: str) -> str:
    if name in COSMOLOGY_NAMES:
        return "cosmology"
    if name.startswith("b"):
        return "bias"
    if name.startswith("alpha") or name == "ctp":
        return "counterterms"
    if name.startswith("sn") or "FoG" in name:
        return "stochastic_fog"
    return "bias"


def _infer_slider_bounds(name: str, value: float, prior: dict[str, Any] | None, ref: dict[str, Any] | None) -> tuple[float, float]:
    if prior and prior.get("dist") == "uniform":
        bounds = _finite_pair(prior.get("limits"))
        if bounds is not None:
            return bounds
    if prior and prior.get("dist") == "norm":
        loc = float(prior.get("loc", value))
        scale = float(prior.get("scale", 1.0))
        width = max(4.0 * scale, 1e-4)
        return loc - width, loc + width
    if ref and ref.get("dist") == "norm":
        loc = float(ref.get("loc", value))
        scale = float(ref.get("scale", max(abs(value) * 0.1, 0.1)))
        width = max(8.0 * scale, 1e-4)
        return loc - width, loc + width
    if name == "X_FoG_pp":
        return 0.0, 10.0
    scale = max(abs(value), 1.0)
    return value - 2.0 * scale, value + 2.0 * scale


def _infer_step(low: float, high: float) -> float:
    width = max(high - low, 1e-8)
    return float(width / 200.0)


def _plot_probe_bounds(spec: dict[str, Any], category: str) -> tuple[float, float]:
    value = float(spec["value"])
    low = float(spec["min"])
    high = float(spec["max"])
    fraction = PLOT_RANGE_FRACTIONS.get(category, 0.3)
    width = max(high - low, 1e-8)
    half_window = 0.5 * fraction * width
    return max(low, value - half_window), min(high, value + half_window)


@dataclass(frozen=True)
class ModelSpec:
    key: str
    label: str
    theory_cls_name: str
    kwargs: dict[str, Any]
    emulator_order: int = 2


class TheoryManager:
    def __init__(self, cache_root: str | Path = ".cache") -> None:
        self.cache_root = Path(cache_root).resolve()
        self.cache_root.mkdir(parents=True, exist_ok=True)
        _configure_environment(self.cache_root)
        self._lock = threading.Lock()
        self._models = {
            "folpsv2": ModelSpec(
                key="folpsv2",
                label="FOLPSv2",
                theory_cls_name="FOLPSv2TracerPowerSpectrumMultipoles",
                kwargs={"prior_basis": "physical_aap", "damping": "lor", "b3_coev": True},
            ),
            "rept": ModelSpec(
                key="rept",
                label="REPT Velocileptors",
                theory_cls_name="REPTVelocileptorsTracerPowerSpectrumMultipoles",
                kwargs={},
            ),
        }
        self._metadata: dict[str, dict[str, Any]] = {}
        self._theories: dict[tuple[str, str], Any] = {}

    def _load_desilike(self) -> None:
        from cosmoprimo.fiducial import DESI
        from desilike.emulators import EmulatedCalculator, Emulator, TaylorEmulatorEngine
        from desilike.theories.galaxy_clustering import (
            DirectPowerSpectrumTemplate,
            FOLPSv2TracerPowerSpectrumMultipoles,
            REPTVelocileptorsTracerPowerSpectrumMultipoles,
        )

        self._DESI = DESI
        self._DirectPowerSpectrumTemplate = DirectPowerSpectrumTemplate
        self._EmulatedCalculator = EmulatedCalculator
        self._Emulator = Emulator
        self._TaylorEmulatorEngine = TaylorEmulatorEngine
        self._theory_classes = {
            "FOLPSv2TracerPowerSpectrumMultipoles": FOLPSv2TracerPowerSpectrumMultipoles,
            "REPTVelocileptorsTracerPowerSpectrumMultipoles": REPTVelocileptorsTracerPowerSpectrumMultipoles,
        }

    def _base_runtime_config(self) -> dict[str, Any]:
        return {"template": self._DirectPowerSpectrumTemplate(fiducial=self._DESI(), z=Z), "ells": ELLS, "k": K_GRID}

    def _emulator_cache_path(self, spec: ModelSpec) -> Path:
        payload = {"model": spec.key, "kwargs": spec.kwargs, "z": Z, "ells": ELLS, "k": [float(KMIN), float(KMAX), float(DK)]}
        digest = hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:10]
        return self.cache_root / "emulators" / f"{spec.key}_{digest}.npy"

    def _build_theory(self, model_key: str, backend: str) -> Any:
        if not hasattr(self, "_DESI"):
            self._load_desilike()
        spec = self._models[model_key]
        theory_cls = self._theory_classes[spec.theory_cls_name]
        theory = theory_cls(**self._base_runtime_config(), **spec.kwargs)
        if backend != "emulated":
            return theory

        cache_fn = self._emulator_cache_path(spec)
        cache_fn.parent.mkdir(parents=True, exist_ok=True)
        if cache_fn.exists():
            LOGGER.info("Loading emulator from %s", cache_fn)
            theory.init.update(pt=self._EmulatedCalculator.load(cache_fn))
            return theory

        LOGGER.info("Building emulator for %s at %s", model_key, cache_fn)
        emulator = self._Emulator(theory.pt, engine=self._TaylorEmulatorEngine(method="finite", order=spec.emulator_order))
        emulator.set_samples()
        emulator.fit()
        emulated_pt = emulator.to_calculator()
        emulated_pt.save(cache_fn)
        theory.init.update(pt=self._EmulatedCalculator.load(cache_fn))
        return theory

    def _get_theory(self, model_key: str, backend: str) -> Any:
        cache_key = (model_key, backend)
        if cache_key not in self._theories:
            self._theories[cache_key] = self._build_theory(model_key, backend)
        return self._theories[cache_key]

    def _parameter_metadata(self, model_key: str) -> dict[str, Any]:
        if model_key in self._metadata:
            return self._metadata[model_key]

        theory = self._get_theory(model_key, "direct")
        groups: dict[str, list[dict[str, Any]]] = {name: [] for name in VISIBLE_CATEGORIES}
        defaults: dict[str, float] = {}

        for param in theory.all_params:
            name = param.basename
            if name not in PARAM_LABELS:
                continue
            fixed = bool(param.fixed)
            if fixed:
                continue
            value = float(param.value)
            prior = _prior_to_dict(getattr(param, "prior", None))
            ref = _ref_to_dict(getattr(param, "ref", None))
            low, high = _infer_slider_bounds(name, value, prior, ref)
            category = _categorize_param(name)
            spec = {
                "name": name,
                "label": PARAM_LABELS.get(name, name),
                "category": category,
                "value": value,
                "min": low,
                "max": high,
                "step": _infer_step(low, high),
                "prior": prior,
                "ref": ref,
            }
            groups[category].append(spec)
            defaults[name] = value

        for category, items in groups.items():
            items.sort(key=lambda item: item["label"])
            groups[category] = items

        result = {"defaults": defaults, "groups": groups, "plot_limits": self._plot_limits(model_key, defaults, groups)}
        self._metadata[model_key] = result
        return result

    def _plot_limits(
        self, model_key: str, defaults: dict[str, float], groups: dict[str, list[dict[str, Any]]]
    ) -> dict[str, dict[str, dict[str, float]]]:
        theory = self._get_theory(model_key, "direct")
        category_envelopes: dict[str, dict[str, dict[str, float]]] = {}

        with self._lock:
            for category, specs in groups.items():
                envelopes = {str(ell): {"min": np.inf, "max": -np.inf} for ell in ELLS}
                trial_points = [dict(defaults)]
                for spec in specs:
                    probe_low, probe_high = _plot_probe_bounds(spec, category)
                    for edge in [probe_low, probe_high]:
                        varied = dict(defaults)
                        varied[spec["name"]] = edge
                        trial_points.append(varied)

                for values in trial_points:
                    poles = np.asarray(theory(**values), dtype=float)
                    scaled = poles * K_GRID[None, :]
                    for index, ell in enumerate(ELLS):
                        envelopes[str(ell)]["min"] = min(envelopes[str(ell)]["min"], float(np.min(scaled[index])))
                        envelopes[str(ell)]["max"] = max(envelopes[str(ell)]["max"], float(np.max(scaled[index])))

                for bounds in envelopes.values():
                    span = max(bounds["max"] - bounds["min"], 1e-8)
                    pad = 0.04 * span
                    bounds["min"] -= pad
                    bounds["max"] += pad

                category_envelopes[category] = envelopes

        return category_envelopes

    def app_config(self) -> dict[str, Any]:
        models = []
        for model_key, spec in self._models.items():
            metadata = self._parameter_metadata(model_key)
            models.append(
                {
                    "key": model_key,
                    "label": spec.label,
                    "defaults": metadata["defaults"],
                    "parameter_groups": metadata["groups"],
                    "plot_limits": metadata["plot_limits"],
                }
            )
        return {
            "app": {
                "title": "Galaxy Clustering Slider",
                "subtitle": "Interactive DESI-like perturbation theory demo for galaxy power spectrum multipoles.",
                "default_model": DEFAULT_MODEL,
                "default_backend": DEFAULT_BACKEND,
                "category_labels": CATEGORY_LABELS,
                "category_order": CATEGORY_ORDER,
            },
            "setup": {
                "tracer": TRACER,
                "z": Z,
                "ells": list(ELLS),
                "k_min": KMIN,
                "k_max": KMAX,
                "dk": DK,
                "n_k": int(K_GRID.size),
            },
            "models": models,
            "backends": [
                {"key": "direct", "label": "Direct"},
                {"key": "emulated", "label": "Emulated"},
            ],
        }

    def evaluate(self, model_key: str, backend: str, params: dict[str, Any]) -> dict[str, Any]:
        if model_key not in self._models:
            raise ValueError(f"Unknown model '{model_key}'")
        if backend not in {"direct", "emulated"}:
            raise ValueError(f"Unknown backend '{backend}'")

        metadata = self._parameter_metadata(model_key)
        values = dict(metadata["defaults"])
        for name, value in params.items():
            if name in values:
                values[name] = float(value)

        with self._lock:
            theory = self._get_theory(model_key, backend)
            start = time.perf_counter()
            poles = np.asarray(theory(**values), dtype=float)
            elapsed_ms = (time.perf_counter() - start) * 1000.0

        return {
            "model": model_key,
            "backend": backend,
            "elapsed_ms": elapsed_ms,
            "k": K_GRID.tolist(),
            "ells": list(ELLS),
            "poles": {str(ell): poles[index].tolist() for index, ell in enumerate(ELLS)},
            "values": values,
        }
