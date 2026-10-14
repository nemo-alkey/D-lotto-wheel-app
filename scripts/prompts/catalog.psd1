@{
    Prompts = @(
        # ---- Runnable: has backing code ----

        @{ Id = 4;  Title = "Scrape historical draws";        Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\backfill_draws.py" } }
        @{ Id = 5;  Title = "Selenium scraper";               Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "selenium_scraper.py" } }
        @{ Id = 6;  Title = "Repair scraped data";            Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\repair_powerball_zero.py" } }
        @{ Id = 8;  Title = "Frequency / hot-cold";           Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\frequency.py" } }
        @{ Id = 9;  Title = "Chi-square uniformity";          Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\chi_square.py" } }
        @{ Id = 10; Title = "Autocorrelation / runs test";    Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\runs_test.py" } }
        @{ Id = 12; Title = "Compare model architectures";    Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\architectures.py" } }
        @{ Id = 13; Title = "Feature engineering pipeline";   Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\features.py" } }
        @{ Id = 14; Title = "ML framing (multi-label)";       Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\framing.py" } }
        @{ Id = 15; Title = "Train with time split";          Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python train_ml_model.py --db data\lotto.db" } }
        @{ Id = 16; Title = "Overfitting / cross-val";        Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\overfitting.py" } }
        @{ Id = 17; Title = "Simulate vs random";             Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\simulate_random.py" } }
        @{ Id = 18; Title = "Hyperparameter tuning (Optuna)"; Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\optuna_tune.py" } }
        @{ Id = 21; Title = "Top-5 candidate sets";           Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\candidate_sets.py" } }
        @{ Id = 22; Title = "Prediction report template";     Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\prediction_report.py" } }
        @{ Id = 23; Title = "Game-specific pipeline deltas";  Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\game_deltas.py" } }
        @{ Id = 24; Title = "Expected value analysis";        Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\ev_table.py" } }
        @{ Id = 28; Title = "Non-obvious AI strategies";      Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\analysis\nonobvious.py" } }
        @{ Id = 32; Title = "Review code (pytest)";           Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python -m pytest tests/ -q" } }
        @{ Id = 33; Title = "Review code (mypy)";             Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python -m mypy ." } }

        # ---- Advisory: emit as text ----
        @{ Id = 2;  Title = "Folder structure";               Category = "Advisory"; Prompt = "Design the folder structure for a lottery prediction project: raw data, cleaned data, notebooks, models, results, and logs. Explain what goes where." }
        @{ Id = 3;  Title = "Local vs Colab";                 Category = "Advisory"; Prompt = "Should I run this project locally or on Google Colab? Compare compute, cost, and convenience for training a small neural network on lottery history data." }
        @{ Id = 7;  Title = "20-year data schema";            Category = "Advisory"; Prompt = "Design a data schema for storing 20 years of lottery draws that supports both frequency analysis and sequence modeling. Include draw metadata like jackpot size and rollover flags." }
        @{ Id = 11; Title = "Skeptical statistician review";  Category = "Advisory"; Prompt = "Act as a skeptical statistician. Review my analysis and identify where I might be falling for the gambler's fallacy, apophenia, or survivorship bias." }
        @{ Id = 19; Title = "Diagnose prediction errors";     Category = "Advisory"; Prompt = "Here are my model's prediction errors. Diagnose what's wrong and suggest the top 3 adjustments - data quality, feature selection, or architecture changes." }
        @{ Id = 20; Title = "Train/test gap debugging";       Category = "Advisory"; Prompt = "My model performs great on training data but terribly on recent draws. Walk me through debugging this step by step." }
        @{ Id = 25; Title = "Bankroll system";                Category = "Advisory"; Prompt = "Design a strict lottery bankroll system for me: weekly budget cap, loss limits, and a rule that lottery spend never exceeds entertainment budget. Include a tracking spreadsheet layout." }
        @{ Id = 26; Title = "Syndicate rules";                Category = "Advisory"; Prompt = "Evaluate whether joining a lottery pool/syndicate improves my expected value versus playing solo, and draft fair rules for a 10-person pool." }
        @{ Id = 27; Title = "Responsible gambling check";     Category = "Advisory"; Prompt = "Act as a responsible-gambling advisor. Review my project and playing habits and flag any warning signs." }
        @{ Id = 29; Title = "Emerging AI techniques";         Category = "Advisory"; Prompt = "Research prompt: what emerging AI techniques (transformers, generative models, anomaly detection) could apply to lottery data, and what are their honest limitations given true randomness?" }
        @{ Id = 30; Title = "Project coach";                  Category = "Advisory"; Prompt = "You are my lottery-AI project coach. Based on Covella's approach, ask me 10 questions to assess my current progress, then give me a personalized next-steps roadmap." }
    )
}
