"""
Calibration Models & Analytical Chemistry Regression Engine
Implements Beer-Lambert Linear, Polynomial (Quadratic), 4-Parameter Logistic (4PL),
Multivariate Ridge, and Random Forest models with LOD, LOQ, and 95% Confidence Intervals.
"""

import numpy as np
from scipy.optimize import curve_fit
from sklearn.linear_model import Ridge, LinearRegression
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import r2_score, mean_squared_error, mean_absolute_error
from typing import Dict, Any, List, Tuple, Optional
import os
import joblib


def four_pl_func(x, a, b, c, d):
    """
    Standard 4-Parameter Logistic (4PL) sigmoidal equation:
    y = d + (a - d) / (1 + (x / c)^b)
    """
    eps = 1e-9
    x_safe = np.maximum(x, eps)
    c_safe = max(abs(c), eps)
    return d + (a - d) / (1.0 + np.power(x_safe / c_safe, b))


def four_pl_inverse(y, a, b, c, d):
    """
    Analytical inverse of 4PL equation to calculate concentration x given response y:
    x = c * ((a - d) / (y - d) - 1)^(1 / b)
    """
    eps = 1e-9
    denom = y - d
    if abs(denom) < eps:
        denom = eps if denom >= 0 else -eps

    ratio = (a - d) / denom - 1.0
    if ratio <= 0:
        # If response is beyond asymptotes, clamp safely
        return 0.0 if (y - a)**2 < (y - d)**2 else abs(c) * 2.0

    b_safe = b if abs(b) > 1e-4 else 1.0
    return abs(c) * np.power(ratio, 1.0 / b_safe)


class CalibrationEngine:
    """
    Unified Calibration and Quantitation Engine.
    Trains and benchmarks multiple regression models simultaneously,
    calculates laboratory quality metrics (LOD, LOQ, R2, RMSE),
    and predicts concentrations with 95% confidence intervals.
    """

    FEATURE_NAMES = [
        "mean_r", "mean_g", "mean_b",
        "std_r", "std_g", "std_b",
        "mean_L", "mean_a", "mean_b_lab",
        "mean_h", "mean_s", "mean_v",
        "mean_gray",
        "ratio_rg", "ratio_bg", "ratio_rb",
        "od_r", "od_g", "od_b",
        "delta_E"
    ]

    def __init__(self, analyte_name: str = "Analyte", unit: str = "µg/mL"):
        self.analyte_name = analyte_name
        self.unit = unit
        self.trained = False
        self.best_model_name = "linear"
        self.models = {}
        self.metrics = {}
        self.fitted_curve_data = {}
        self.feature_importance = {}
        self.scaler = None
        self.primary_signal_key = "od_b"  # Default single-channel optical signal
        self.concentrations_train = []
        self.signals_train = []
        self.feature_vectors_train = []

    def _determine_best_single_signal(self, features_list: List[Dict[str, Any]], concentrations: List[float]) -> str:
        """
        Auto-identify the single color channel / optical density metric with the strongest
        monotonic correlation (|Pearson r|) with concentration.
        """
        candidates = ["od_b", "od_g", "od_r", "od_gray", "mean_gray", "delta_E", "mean_L", "mean_s", "ratio_bg"]
        y = np.array(concentrations, dtype=np.float64)
        best_candidate = "od_b"
        best_corr = -1.0

        for cand in candidates:
            vals = np.array([f.get(cand, 0.0) for f in features_list], dtype=np.float64)
            if np.std(vals) > 1e-6 and np.std(y) > 1e-6:
                corr = abs(np.corrcoef(vals, y)[0, 1])
                if corr > best_corr:
                    best_corr = corr
                    best_candidate = cand

        return best_candidate

    def train(self, samples: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Train all regression models on standard calibration samples.
        Each sample must have 'concentration' (float) and 'features' (dict).
        """
        if len(samples) < 2:
            raise ValueError("At least 2 calibration standard points are required for calibration.")

        # Sort samples by concentration
        samples = sorted(samples, key=lambda s: float(s["concentration"]))
        concentrations = np.array([float(s["concentration"]) for s in samples], dtype=np.float64)
        features_list = [s["features"] for s in samples]

        self.concentrations_train = concentrations
        self.primary_signal_key = self._determine_best_single_signal(features_list, concentrations.tolist())
        signals = np.array([f.get(self.primary_signal_key, 0.0) for f in features_list], dtype=np.float64)
        self.signals_train = signals

        X_multivar = np.array([f.get("feature_vector", [0.0]*20) for f in features_list], dtype=np.float64)
        self.feature_vectors_train = X_multivar

        self.scaler = StandardScaler()
        X_scaled = self.scaler.fit_transform(X_multivar)

        n_samples = len(concentrations)
        metrics_dict = {}

        # -------------------------------------------------------------
        # 1. Beer-Lambert Linear Model: Signal = m * Conc + c
        # -------------------------------------------------------------
        lin_reg = LinearRegression()
        lin_reg.fit(concentrations.reshape(-1, 1), signals)
        m_slope = float(lin_reg.coef_[0])
        c_intercept = float(lin_reg.intercept_)
        pred_signals_lin = lin_reg.predict(concentrations.reshape(-1, 1))
        r2_lin = float(max(0.0, r2_score(signals, pred_signals_lin)))
        rmse_lin = float(np.sqrt(mean_squared_error(signals, pred_signals_lin)))
        mae_lin = float(mean_absolute_error(signals, pred_signals_lin))

        self.models["linear"] = {
            "type": "linear",
            "slope": m_slope,
            "intercept": c_intercept,
            "signal_key": self.primary_signal_key,
            "formula": f"Signal = {m_slope:.4f} × C + {c_intercept:.4f}"
        }
        metrics_dict["linear"] = {
            "name": "Beer-Lambert Linear",
            "r2": round(r2_lin, 4),
            "rmse": round(rmse_lin, 5),
            "mae": round(mae_lin, 5),
            "slope": round(m_slope, 4),
            "intercept": round(c_intercept, 4)
        }

        # -------------------------------------------------------------
        # 2. Polynomial Degree 2 Model: Signal = a*C^2 + b*C + c
        # -------------------------------------------------------------
        poly_deg = 2 if n_samples >= 3 else 1
        poly_coeffs = np.polyfit(concentrations, signals, deg=poly_deg)
        pred_signals_poly = np.polyval(poly_coeffs, concentrations)
        r2_poly = float(max(0.0, r2_score(signals, pred_signals_poly)))
        rmse_poly = float(np.sqrt(mean_squared_error(signals, pred_signals_poly)))
        mae_poly = float(mean_absolute_error(signals, pred_signals_poly))

        self.models["polynomial"] = {
            "type": "polynomial",
            "degree": poly_deg,
            "coeffs": poly_coeffs.tolist(),
            "signal_key": self.primary_signal_key
        }
        metrics_dict["polynomial"] = {
            "name": "Polynomial (Degree 2)" if poly_deg == 2 else "Polynomial (Degree 1)",
            "r2": round(r2_poly, 4),
            "rmse": round(rmse_poly, 5),
            "mae": round(mae_poly, 5)
        }

        # -------------------------------------------------------------
        # 3. 4-Parameter Logistic (4PL) Curve Model
        # -------------------------------------------------------------
        if n_samples >= 4:
            try:
                # Initial parameter guesses: a=min(signals), d=max(signals), c=median(conc), b=1.0
                a0 = float(signals[0])
                d0 = float(signals[-1])
                c0 = float(np.median(concentrations)) if np.median(concentrations) > 0 else 1.0
                b0 = 1.0 if d0 >= a0 else -1.0

                popt, _ = curve_fit(
                    four_pl_func,
                    concentrations,
                    signals,
                    p0=[a0, b0, c0, d0],
                    bounds=([min(signals) - 50, -10.0, 1e-4, min(signals) - 50],
                            [max(signals) + 50, 10.0, max(concentrations) * 10, max(signals) + 50]),
                    maxfev=5000
                )
                pred_signals_4pl = four_pl_func(concentrations, *popt)
                r2_4pl = float(max(0.0, r2_score(signals, pred_signals_4pl)))
                rmse_4pl = float(np.sqrt(mean_squared_error(signals, pred_signals_4pl)))
                mae_4pl = float(mean_absolute_error(signals, pred_signals_4pl))

                self.models["four_pl"] = {
                    "type": "four_pl",
                    "params": popt.tolist(),
                    "signal_key": self.primary_signal_key
                }
                metrics_dict["four_pl"] = {
                    "name": "4-Parameter Logistic (4PL)",
                    "r2": round(r2_4pl, 4),
                    "rmse": round(rmse_4pl, 5),
                    "mae": round(mae_4pl, 5),
                    "a": round(float(popt[0]), 4),
                    "b": round(float(popt[1]), 4),
                    "c": round(float(popt[2]), 4),
                    "d": round(float(popt[3]), 4)
                }
            except Exception:
                # If 4PL convergence fails, fall back gracefully
                pass

        # -------------------------------------------------------------
        # 4. Multivariate Ridge Regression Model
        # -------------------------------------------------------------
        ridge = Ridge(alpha=1.0)
        ridge.fit(X_scaled, concentrations)
        pred_conc_ridge = ridge.predict(X_scaled)
        r2_ridge = float(max(0.0, r2_score(concentrations, pred_conc_ridge)))
        rmse_ridge = float(np.sqrt(mean_squared_error(concentrations, pred_conc_ridge)))
        mae_ridge = float(mean_absolute_error(concentrations, pred_conc_ridge))

        self.models["ridge"] = {
            "type": "ridge",
            "model": ridge,
            "signal_key": "multivariate"
        }
        metrics_dict["ridge"] = {
            "name": "Multivariate Ridge",
            "r2": round(r2_ridge, 4),
            "rmse": round(rmse_ridge, 4),
            "mae": round(mae_ridge, 4)
        }

        # -------------------------------------------------------------
        # 5. Random Forest Regressor Model (if n_samples >= 4)
        # -------------------------------------------------------------
        if n_samples >= 4:
            rf = RandomForestRegressor(n_estimators=50, random_state=42, max_depth=4)
            rf.fit(X_scaled, concentrations)
            pred_conc_rf = rf.predict(X_scaled)
            r2_rf = float(max(0.0, r2_score(concentrations, pred_conc_rf)))
            rmse_rf = float(np.sqrt(mean_squared_error(concentrations, pred_conc_rf)))
            mae_rf = float(mean_absolute_error(concentrations, pred_conc_rf))

            self.models["random_forest"] = {
                "type": "random_forest",
                "model": rf,
                "signal_key": "multivariate"
            }
            metrics_dict["random_forest"] = {
                "name": "Random Forest Ensemble",
                "r2": round(r2_rf, 4),
                "rmse": round(rmse_rf, 4),
                "mae": round(mae_rf, 4)
            }

            # Feature importance ranking
            importances = rf.feature_importances_
            sorted_idx = np.argsort(importances)[::-1][:6]
            self.feature_importance = {
                self.FEATURE_NAMES[i]: round(float(importances[i]), 4)
                for i in sorted_idx
            }

        # -------------------------------------------------------------
        # Select Best Model based on R2 and RMSE
        # -------------------------------------------------------------
        best_name = "linear"
        best_score = -999.0
        for name, m in metrics_dict.items():
            score = m["r2"] - (0.05 * m["rmse"])
            if score > best_score:
                best_score = score
                best_name = name

        self.best_model_name = best_name
        self.metrics = metrics_dict

        # -------------------------------------------------------------
        # Calculate Analytical Chemistry Limits (LOD & LOQ)
        # LOD = 3.3 * sigma_blank / |slope|
        # LOQ = 10 * sigma_blank / |slope|
        # -------------------------------------------------------------
        # Blank response estimation (sample with lowest concentration)
        blank_idx = np.argmin(concentrations)
        blank_features = features_list[blank_idx]
        sigma_blank = blank_features.get("std_gray", 1.5) / 255.0
        slope_abs = abs(m_slope) if abs(m_slope) > 1e-5 else 1e-4

        lod = float(3.3 * sigma_blank / slope_abs)
        loq = float(10.0 * sigma_blank / slope_abs)
        lod = round(max(0.01, min(lod, float(np.max(concentrations)) * 0.2)), 3)
        loq = round(max(lod * 2.0, min(loq, float(np.max(concentrations)) * 0.4)), 3)

        c_min = float(np.min(concentrations))
        c_max = float(np.max(concentrations))

        # -------------------------------------------------------------
        # Generate High-Resolution Curve Points for Plotly Chart
        # -------------------------------------------------------------
        x_dense = np.linspace(c_min, c_max * 1.15, 100)
        y_dense_linear = (m_slope * x_dense + c_intercept).tolist()
        y_dense_poly = np.polyval(poly_coeffs, x_dense).tolist()

        y_dense_4pl = []
        if "four_pl" in self.models:
            params_4pl = self.models["four_pl"]["params"]
            y_dense_4pl = four_pl_func(x_dense, *params_4pl).tolist()

        self.fitted_curve_data = {
            "x_dense": [round(float(v), 4) for v in x_dense],
            "y_dense_linear": [round(float(v), 4) for v in y_dense_linear],
            "y_dense_poly": [round(float(v), 4) for v in y_dense_poly],
            "y_dense_4pl": [round(float(v), 4) for v in y_dense_4pl] if y_dense_4pl else None,
            "x_exp": [round(float(v), 4) for v in concentrations],
            "y_exp": [round(float(v), 4) for v in signals],
            "primary_signal_key": self.primary_signal_key,
            "lod": lod,
            "loq": loq,
            "c_min": c_min,
            "c_max": c_max
        }

        self.trained = True

        return {
            "best_model": self.best_model_name,
            "primary_signal": self.primary_signal_key,
            "metrics": self.metrics,
            "lod": lod,
            "loq": loq,
            "linear_range": [c_min, c_max],
            "feature_importance": self.feature_importance,
            "curve_data": self.fitted_curve_data
        }

    def predict(self, sample_features: Dict[str, Any], model_override: Optional[str] = None) -> Dict[str, Any]:
        """
        Predict concentration of an unknown sample.
        Calculates 95% Confidence Interval and dynamic range quality flags.
        """
        if not self.trained:
            raise RuntimeError("Model has not been trained yet. Calibrate with standards first.")

        model_name = model_override or self.best_model_name
        if model_name not in self.models:
            model_name = "linear"

        signal_val = sample_features.get(self.primary_signal_key, 0.0)
        feature_vector = sample_features.get("feature_vector", [0.0]*20)

        pred_concentration = 0.0

        if model_name == "linear":
            lin_info = self.models["linear"]
            m = lin_info["slope"]
            c = lin_info["intercept"]
            if abs(m) > 1e-6:
                pred_concentration = (signal_val - c) / m
            else:
                pred_concentration = 0.0

        elif model_name == "polynomial":
            poly_info = self.models["polynomial"]
            coeffs = poly_info["coeffs"]
            if len(coeffs) == 3:
                # a*C^2 + b*C + (c - y) = 0
                a, b, c = coeffs[0], coeffs[1], coeffs[2] - signal_val
                discriminant = b**2 - 4*a*c
                if discriminant >= 0 and abs(a) > 1e-7:
                    root1 = (-b + np.sqrt(discriminant)) / (2*a)
                    root2 = (-b - np.sqrt(discriminant)) / (2*a)
                    c_max = self.fitted_curve_data.get("c_max", 100.0)
                    # Pick root that falls in physical range [0, 1.5 * c_max]
                    candidates = [r for r in [root1, root2] if -0.1 <= r <= c_max * 1.5]
                    pred_concentration = candidates[0] if candidates else max(0.0, root1)
                else:
                    # Fall back to linear
                    pred_concentration = (signal_val - self.models["linear"]["intercept"]) / self.models["linear"]["slope"]
            else:
                pred_concentration = (signal_val - coeffs[1]) / (coeffs[0] + 1e-6)

        elif model_name == "four_pl" and "four_pl" in self.models:
            popt = self.models["four_pl"]["params"]
            pred_concentration = four_pl_inverse(signal_val, *popt)

        elif model_name in ["ridge", "random_forest"]:
            X_scaled = self.scaler.transform([feature_vector])
            ml_model = self.models[model_name]["model"]
            pred_concentration = float(ml_model.predict(X_scaled)[0])

        # Clamp physically negative predictions to 0.0
        pred_concentration = max(0.0, float(pred_concentration))

        # Calculate 95% Confidence Interval (approx ± 1.96 * RMSE_of_model)
        model_rmse = self.metrics.get(model_name, {}).get("rmse", 0.05)
        # Convert signal RMSE to concentration domain using sensitivity slope
        slope_abs = abs(self.models["linear"]["slope"]) if abs(self.models["linear"]["slope"]) > 1e-5 else 1.0
        conc_uncertainty = (model_rmse / slope_abs) * 1.96
        ci_lower = max(0.0, pred_concentration - conc_uncertainty)
        ci_upper = pred_concentration + conc_uncertainty

        # Range and Quality Flags
        lod = self.fitted_curve_data.get("lod", 0.0)
        loq = self.fitted_curve_data.get("loq", 0.0)
        c_max = self.fitted_curve_data.get("c_max", 100.0)

        if pred_concentration < lod:
            status_flag = "Below LOD (< Limit of Detection)"
            status_color = "#f59e0b"  # amber
            confidence = "Low (Below Quantitation Limit)"
        elif pred_concentration < loq:
            status_flag = "Quantifiable with Uncertainty (LOD - LOQ)"
            status_color = "#3b82f6"  # blue
            confidence = "Moderate"
        elif pred_concentration <= c_max:
            status_flag = "Optimal Dynamic Range"
            status_color = "#10b981"  # emerald green
            confidence = "High (95% Analytical Confidence)"
        else:
            status_flag = "Above Dynamic Range (Saturated - Extrapolated)"
            status_color = "#ef4444"  # red
            confidence = "Extrapolated (Dilution Recommended)"

        return {
            "predicted_concentration": round(pred_concentration, 3),
            "unit": self.unit,
            "confidence_interval_95": [round(ci_lower, 3), round(ci_upper, 3)],
            "uncertainty": round(conc_uncertainty, 3),
            "model_used": model_name,
            "status_flag": status_flag,
            "status_color": status_color,
            "confidence": confidence,
            "signal_value": round(float(signal_val), 4),
            "signal_key": self.primary_signal_key,
            "projected_point": {
                "x": round(pred_concentration, 3),
                "y": round(float(signal_val), 4)
            }
        }

    def save_state(self, filepath: str):
        """Save the calibrated state to a joblib bundle."""
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        bundle = {
            "analyte_name": self.analyte_name,
            "unit": self.unit,
            "trained": self.trained,
            "best_model_name": self.best_model_name,
            "models": self.models,
            "metrics": self.metrics,
            "fitted_curve_data": self.fitted_curve_data,
            "feature_importance": self.feature_importance,
            "scaler": self.scaler,
            "primary_signal_key": self.primary_signal_key
        }
        joblib.dump(bundle, filepath)

    def load_state(self, filepath: str):
        """Load calibrated state from a joblib bundle."""
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"Calibration file not found at: {filepath}")
        bundle = joblib.load(filepath)
        self.analyte_name = bundle.get("analyte_name", "Analyte")
        self.unit = bundle.get("unit", "µg/mL")
        self.trained = bundle.get("trained", False)
        self.best_model_name = bundle.get("best_model_name", "linear")
        self.models = bundle.get("models", {})
        self.metrics = bundle.get("metrics", {})
        self.fitted_curve_data = bundle.get("fitted_curve_data", {})
        self.feature_importance = bundle.get("feature_importance", {})
        self.scaler = bundle.get("scaler", None)
        self.primary_signal_key = bundle.get("primary_signal_key", "od_b")
