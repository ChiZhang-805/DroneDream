-- The public catalog contains seven managed choices across these three
-- providers. Credentials remain server-side; this only enables the bounded
-- provider policies consumed by model-gateway.

update public.model_provider_policies
set enabled = true,
    assistant_enabled = true,
    job_enabled = true,
    version = version + 1,
    updated_at = now()
where provider in ('openai', 'deepseek', 'kimi')
  and not (enabled and assistant_enabled and job_enabled);
