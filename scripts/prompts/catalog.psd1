@{
    Prompts = @(
        # ---- Runnable: has backing code ----
      
        @{ Id = 4;  Title = "Scrape historical draws";        Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\backfill_draws.py" } }
        @{ Id = 5;  Title = "Selenium scraper";               Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "selenium_scraper.py" } }
        @{ Id = 6;  Title = "Repair scraped data";            Category = "Runnable";    Dispatch = @{ Type = "Script"; Path = "scripts\repair_powerball_zero.py" } }
        @{ Id = 15; Title = "Train with time split";          Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python train_ml_model.py --db data\lotto.db" } }
        @{ Id = 32; Title = "Review code (pytest)";           Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python -m pytest tests/ -q" } }
        @{ Id = 33; Title = "Review code (mypy)";             Category = "Runnable";    Dispatch = @{ Type = "Shell";  Path = "python -m mypy ." } }

        # ---- NeedsScript: not yet implemented ----
        @{ Id = 8;  Title = "Frequency / hot-cold";           Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.frequency" } }
        @{ Id = 9;  Title = "Chi-square uniformity";          Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.chi_square" } }
        @{ Id = 10; Title = "Autocorrelation / runs test";    Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.runs_test" } }
        @{ Id = 12; Title = "Compare model architectures";    Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.architectures" } }
        @{ Id = 13; Title = "Feature engineering pipeline";   Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.features" } }
        @{ Id = 14; Title = "ML framing (multi-label)";       Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.framing" } }
        @{ Id = 16; Title = "Overfitting / cross-val";        Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.overfitting" } }
        @{ Id = 17; Title = "Simulate vs random";             Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.simulate_random" } }
        @{ Id = 18; Title = "Hyperparameter tuning (Optuna)"; Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.optuna_tune" } }
        @{ Id = 21; Title = "Top-5 candidate sets";           Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.candidate_sets" } }
        @{ Id = 22; Title = "Prediction report template";     Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.prediction_report" } }
        @{ Id = 23; Title = "Game-specific pipeline deltas";  Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.game_deltas" } }
        @{ Id = 24; Title = "Expected value analysis";        Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.ev_table" } }
        @{ Id = 28; Title = "Non-obvious AI strategies";      Category = "NeedsScript"; Dispatch = @{ Type = "PythonModule"; Module = "scripts.analysis.nonobvious" } }

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
