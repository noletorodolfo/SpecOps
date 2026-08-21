# ML Pipeline Patterns (summary)
- Reproducibility comes from pinning three things together, not one: code version, data version, and model/hyperparameter version — losing any one makes "why did this prediction happen" unanswerable.
- Separate the training pipeline from the serving path; training can be batch/slow, serving needs its own latency and rollback story independent of when the model was last retrained.
- Feature computation must be identical between training and serving (avoid training/serving skew) — prefer a shared feature-transformation module over reimplementing logic twice.
- Practical note: log input distributions in production, not just accuracy — silent data drift is the most common way a previously-good model quietly degrades.
