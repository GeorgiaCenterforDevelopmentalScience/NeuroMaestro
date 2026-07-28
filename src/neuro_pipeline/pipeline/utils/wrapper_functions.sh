#!/bin/bash

# Report a failed logging call. Needed because these calls are piped into tee,
# so $? reflects tee rather than the command; callers pass ${PIPESTATUS[0]}.
warn_if_failed() {
    local status="$1"
    local what="$2"
    if [ "${status:-0}" -ne 0 ]; then
        echo "WARNING: Failed to $what (exit $status)" | tee -a "$LOG_PATH"
    fi
}

# Global cleanup handler for signals
cleanup_on_signal() {
    local signal_name="$1"
    local exit_code="$2"
    
    echo "" | tee -a "$LOG_PATH" 2>/dev/null
    echo "=== Job Interrupted: $(date) ===" | tee -a "$LOG_PATH" 2>/dev/null
    echo "Signal: $signal_name (exit code: $exit_code)" | tee -a "$LOG_PATH" 2>/dev/null
    
    # Log cancellation to JSON
    if [ -n "$SUBJECT_ID" ] && [ -n "$TASK_NAME" ] && [ -n "$DB_PATH" ]; then
        echo "Logging cancellation..." | tee -a "$LOG_PATH" 2>/dev/null
        
        # Get full job ID
        local full_job_id="${SLURM_JOB_ID}"
        if [ -n "$SLURM_ARRAY_JOB_ID" ] && [ -n "$SLURM_ARRAY_TASK_ID" ]; then
            full_job_id="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
        else
            full_job_id="${SLURM_JOB_ID}"
        fi
        
        python3 "$SCRIPT_DIR/utils/job_db.py" log_end \
            "$SUBJECT_ID" "$TASK_NAME" "CANCELLED" \
            --exit-code "$exit_code" \
            --error-msg "Job interrupted by $signal_name" \
            --session "${SESSION:-}" \
            --job-id "$full_job_id" \
            --db-path "$DB_PATH" 2>&1 | tee -a "$LOG_PATH"
    fi
    
    echo "Cleanup complete, exiting..." | tee -a "$LOG_PATH" 2>/dev/null
    exit "$exit_code"
}

# Register signal handlers
trap 'cleanup_on_signal SIGTERM 143' SIGTERM
trap 'cleanup_on_signal SIGINT 130' SIGINT
trap 'cleanup_on_signal SIGHUP 129' SIGHUP

# Get SLURM job duration from accounting
get_slurm_duration() {
    local job_id="$1"
    
    if [ -z "$job_id" ]; then
        echo ""
        return
    fi
    
    # Wait for SLURM accounting to update
    sleep 2
    
    # Try to get elapsed time from sacct
    if command -v sacct &> /dev/null; then
        local elapsed=$(sacct -j "$job_id" --format=ElapsedRaw --noheader --parsable2 2>/dev/null | head -n 1 | tr -d ' ')
        
        if [ -n "$elapsed" ] && [ "$elapsed" -gt 0 ]; then
            echo "$elapsed"
            return
        fi
    fi
    
    echo ""
}

# Main wrapper execution function
execute_wrapper() {
    local script_path="$1"
    
    # Parse subjects array
    IFS=' ' read -ra subjects_array <<< "$SUBJECTS"
    NUM_SUBJECTS=${#subjects_array[@]}
    
    # Select subject based on array task ID
    if [ -n "$SLURM_ARRAY_TASK_ID" ] && [ "$NUM_SUBJECTS" -gt 0 ]; then
        local idx=$((SLURM_ARRAY_TASK_ID - 1))
        # Guard against an array range wider than the subject list (e.g. a
        # hard-coded array_config pattern): bash would silently yield "".
        if [ "$idx" -lt 0 ] || [ "$idx" -ge "$NUM_SUBJECTS" ]; then
            echo "Array task $SLURM_ARRAY_TASK_ID has no matching subject (only $NUM_SUBJECTS provided); exiting."
            return 0
        fi
        subject="${subjects_array[$idx]}"
    else
        subject="${subjects_array[0]}"
    fi
    
    # Export for signal handler access
    export SUBJECT_ID="$subject"
    
    # Setup task name
    if [ -n "$TASK_NAME" ]; then
        task_name="$TASK_NAME"
    else
        if [[ "$script_path" == *.py ]]; then
            task_name=$(basename "$script_path" .py)
        else
            task_name=$(basename "$script_path" .sh)
        fi
    fi
    export TASK_NAME="$task_name"
    
    # Setup log directories
    if [ -n "$SLURM_ARRAY_TASK_ID" ]; then
        SUB_LOG_DIR="$LOG_DIR/$task_name/sub-${subject}"
    else
        SUB_LOG_DIR="$LOG_DIR/$task_name"
    fi
    mkdir -p "$SUB_LOG_DIR"
    
    # Create log file with timestamp and job_id
    timestamp=$(date +%Y%m%d_%H%M%S)
    if [ -n "$SLURM_ARRAY_TASK_ID" ]; then
        LOG_PATH="$SUB_LOG_DIR/${task_name}_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID}_${timestamp}.log"
    else
        LOG_PATH="$SUB_LOG_DIR/${task_name}_${SLURM_JOB_ID}_${timestamp}.log"
    fi
    
    export SUB_LOG_DIR LOG_PATH

    # Setup database path
    if [ -z "$DB_PATH" ]; then
        DB_PATH="$WORK_DIR/database/pipeline_jobs.db"
    fi
    export DB_PATH
    export EXECUTION_ID="${EXECUTION_ID:-}"
    
    # Create and source environment file
    create_env_file
    source "$ENV_FILE"
    
    # Execute the actual script with logging
    execute_script_with_logging "$script_path" "$subject" "$task_name"
}

# Create environment file with all necessary variables
create_env_file() {
    ENV_FILE="/tmp/env_${TASK_NAME}_${SLURM_JOB_ID}_${SLURM_ARRAY_TASK_ID:-0}_${subject}_$RANDOM.sh"
    export ENV_FILE
    
    cat > "$ENV_FILE" << 'ENV_EOF'
#!/bin/bash
# Auto-generated environment file
ENV_EOF
    
    # Load global Python environment
    if [ -n "$GLOBAL_PYTHON_COMMANDS" ]; then
        echo "# Load global Python environment" >> "$ENV_FILE"
        echo "$GLOBAL_PYTHON_COMMANDS" >> "$ENV_FILE"
        echo "" >> "$ENV_FILE"
    fi

    # Load environment modules
    if [ -n "$ENV_COMMANDS" ]; then
        echo "# Load environment modules" >> "$ENV_FILE"
        echo "$ENV_COMMANDS" >> "$ENV_FILE"
        echo "" >> "$ENV_FILE"
    fi

    # Re-apply Python isolation after module load / venv activate
    cat >> "$ENV_FILE" << 'PYISO_EOF'
# Python isolation (re-applied after env setup)
export PYTHONNOUSERSITE=1
unset PYTHONPATH
PYISO_EOF
    
    # Export basic variables
    cat >> "$ENV_FILE" << ENV_EOF
# Basic environment variables
export SUBJECT_ID="$subject"
export NUM_SUBJECTS="$NUM_SUBJECTS"
export SUBJECTS_ARRAY="${subjects_array[*]}"
export INPUT_DIR="$INPUT_DIR"
export OUTPUT_DIR="$OUTPUT_DIR"
export WORK_DIR="$WORK_DIR"
export CONTAINER_DIR="$CONTAINER_DIR"
export LOG_DIR="$LOG_DIR"
export DB_PATH="$DB_PATH"
export TASK_NAME="$TASK_NAME"
export SUB_LOG_DIR="$SUB_LOG_DIR"
export LOG_PATH="$LOG_PATH"
export SESSION="${SESSION:-}"
export SCRIPT_DIR="$SCRIPT_DIR"
export EXECUTION_ID="${EXECUTION_ID:-}"
ENV_EOF
    
    # Export global environment variables
    if [ -n "$GLOBAL_ENV_VARS" ]; then
        echo "" >> "$ENV_FILE"
        echo "# Global environment variables" >> "$ENV_FILE"
        echo "$GLOBAL_ENV_VARS" >> "$ENV_FILE"
    fi
    
    # Export task-specific parameters
    if [ -n "$TASK_PARAMS" ]; then
        echo "" >> "$ENV_FILE"
        echo "# Task-specific parameters" >> "$ENV_FILE"
        echo "$TASK_PARAMS" >> "$ENV_FILE"
    fi
}

# Execute script with logging
execute_script_with_logging() {
    local script_path="$1"
    local subject="$2"
    local task_name="$3"
    
    # Verify script exists
    if [ ! -f "$script_path" ]; then
        echo "ERROR: Script not found: $script_path" | tee -a "$LOG_PATH"
        return 127
    fi
    
    local bash_start_time=$(date +%s)
    
    local full_job_id="${SLURM_JOB_ID}"
    if [ -n "$SLURM_ARRAY_JOB_ID" ] && [ -n "$SLURM_ARRAY_TASK_ID" ]; then
        full_job_id="${SLURM_ARRAY_JOB_ID}_${SLURM_ARRAY_TASK_ID}"
    else
        full_job_id="${SLURM_JOB_ID}"
    fi
    
    echo "=== Job Start: $(date) ===" | tee -a "$LOG_PATH"
    echo "Subject: $subject" | tee -a "$LOG_PATH"
    echo "Task: $task_name" | tee -a "$LOG_PATH"
    echo "Script: $script_path" | tee -a "$LOG_PATH"
    echo "SLURM Job ID: ${full_job_id:-N/A}" | tee -a "$LOG_PATH"
    echo "===========================================" | tee -a "$LOG_PATH"
    
    # Log start to JSON
    python3 "$SCRIPT_DIR/utils/job_db.py" log_start \
        "$subject" "$task_name" \
        --log-file-path "$LOG_PATH" \
        --job-id "$full_job_id" \
        --node-list "$SLURM_JOB_NODELIST" \
        --session "${SESSION:-}" \
        --execution-id "${EXECUTION_ID:-}" \
        --db-path "$DB_PATH" 2>&1 | tee -a "$LOG_PATH"
    warn_if_failed "${PIPESTATUS[0]}" "log job start"

    # Execute the script
    if [[ "$script_path" == *.py ]]; then
        python "$script_path" "$subject" >> "$LOG_PATH" 2>&1
    else
        bash "$script_path" "$subject" >> "$LOG_PATH" 2>&1
    fi
    script_status=$?
    
    local bash_end_time=$(date +%s)
    local bash_duration=$((bash_end_time - bash_start_time))
    
    echo "===========================================" | tee -a "$LOG_PATH"
    echo "=== Job End: $(date) ===" | tee -a "$LOG_PATH"
    echo "Exit code: $script_status" | tee -a "$LOG_PATH"
    echo "Bash measured duration: ${bash_duration} seconds" | tee -a "$LOG_PATH"
    
    # Try to get SLURM duration
    local slurm_duration=""
    local final_duration=$bash_duration
    
    if [ -n "$full_job_id" ]; then
        slurm_duration=$(get_slurm_duration "$full_job_id")
        
        if [ -n "$slurm_duration" ] && [ "$slurm_duration" -gt 0 ]; then
            echo "SLURM measured duration: ${slurm_duration} seconds" | tee -a "$LOG_PATH"
            final_duration=$slurm_duration
        fi
    fi
    
    echo "Final recorded duration: ${final_duration} seconds" | tee -a "$LOG_PATH"
    echo "===========================================" | tee -a "$LOG_PATH"
    
    # Log command output (skip for unzip task)
    if [ "$task_name" != "unzip" ]; then
        if [ -f "$LOG_PATH" ]; then
            output_content=$(tail -n 50 "$LOG_PATH" 2>/dev/null || echo "")
        else
            output_content=""
        fi
        
        python3 "$SCRIPT_DIR/utils/job_db.py" log_command_output \
            "$subject" "$task_name" "$(basename "$script_path")" \
            "$script_path $subject" \
            --stdout "$output_content" \
            --exit-code "$script_status" \
            --log-file-path "$LOG_PATH" \
            --job-id "$full_job_id" \
            --session "${SESSION:-}" \
            --execution-id "${EXECUTION_ID:-}" \
            --db-path "$DB_PATH" 2>&1 | tee -a "$LOG_PATH"
        warn_if_failed "${PIPESTATUS[0]}" "log command output"
    fi
    
    # Log end to JSON with job_id
    if [ $script_status -eq 0 ]; then
        python3 "$SCRIPT_DIR/utils/job_db.py" log_end \
            "$subject" "$task_name" "SUCCESS" \
            --exit-code "$script_status" \
            --duration-seconds "$final_duration" \
            --session "${SESSION:-}" \
            --job-id "$full_job_id" \
            --db-path "$DB_PATH" 2>&1 | tee -a "$LOG_PATH"
        warn_if_failed "${PIPESTATUS[0]}" "log job end"
    else
        python3 "$SCRIPT_DIR/utils/job_db.py" log_end \
            "$subject" "$task_name" "FAILED" \
            --error-msg "Script failed with exit code $script_status" \
            --exit-code "$script_status" \
            --duration-seconds "$final_duration" \
            --session "${SESSION:-}" \
            --job-id "$full_job_id" \
            --db-path "$DB_PATH" 2>&1 | tee -a "$LOG_PATH"
        warn_if_failed "${PIPESTATUS[0]}" "log job end"
    fi

    return $script_status
}