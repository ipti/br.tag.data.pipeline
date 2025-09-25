import logging
import inspect
import functools
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path


class AirflowLogger:
    """
    Logger class optimized for use with Apache Airflow.

    Features:
    - Error logs automatically include function name
    - Consistent formatting with clear prefixes
    - Specific methods for Airflow operations (XComs, Tasks)
    - Flexible log level configuration
    """

    def __init__(
        self,
        name: str = "airflow_custom",
        level: int = logging.INFO,
        log_file: Optional[str] = None,
        include_timestamp: bool = True,
    ):
        """
        Initialize the logger.

        Args:
            name: Logger name
            level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            log_file: Path to log file (optional)
            include_timestamp: Whether to include timestamp in logs
        """
        self.logger = logging.getLogger(name)
        self.logger.setLevel(level)
        self.include_timestamp = include_timestamp

        # Remove existing handlers to avoid duplication
        self.logger.handlers.clear()

        # Setup formatting
        self._setup_formatters()

        # Setup handlers
        self._setup_console_handler()

        if log_file:
            self._setup_file_handler(log_file)

    def _setup_formatters(self):
        """Setup log formatters."""
        if self.include_timestamp:
            self.formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        else:
            self.formatter = logging.Formatter("%(name)s - %(levelname)s - %(message)s")

    def _setup_console_handler(self):
        """Setup console handler."""
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(self.formatter)
        self.logger.addHandler(console_handler)

    def _setup_file_handler(self, log_file: str):
        """Setup file handler."""
        # Create directory if it doesn't exist
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(self.formatter)
        self.logger.addHandler(file_handler)

    def _get_caller_function_name(self) -> str:
        """
        Get the name of the function that called the log method.

        Returns:
            Name of the function that called the log
        """
        try:
            # Stack: [0] = _get_caller_function_name, [1] = log method, [2] = calling function
            frame = inspect.currentframe().f_back.f_back
            return frame.f_code.co_name
        except (AttributeError, TypeError):
            return "unknown_function"

    def info(self, message: str, extra_data: Optional[Dict[str, Any]] = None):
        """
        Info log.

        Args:
            message: Message to be logged
            extra_data: Additional data for context
        """
        log_message = f"[INFO] {message}"

        if extra_data:
            log_message += f" | Data: {extra_data}"

        self.logger.info(log_message)

    def error(
        self,
        message: str,
        exception: Optional[Exception] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ):
        """
        Error log with function name.

        Args:
            message: Error message
            exception: Caught exception (optional)
            extra_data: Additional data for context
        """
        function_name = self._get_caller_function_name()
        log_message = f"[ERROR] [{function_name}] {message}"

        if exception:
            log_message += f" | Exception: {str(exception)}"

        if extra_data:
            log_message += f" | Data: {extra_data}"

        self.logger.error(log_message)

    def warning(self, message: str, extra_data: Optional[Dict[str, Any]] = None):
        """
        Warning log.

        Args:
            message: Warning message
            extra_data: Additional data for context
        """
        function_name = self._get_caller_function_name()
        log_message = f"[WARNING] [{function_name}] {message}"

        if extra_data:
            log_message += f" | Data: {extra_data}"

        self.logger.warning(log_message)

    def debug(self, message: str, extra_data: Optional[Dict[str, Any]] = None):
        """
        Debug log with function name.

        Args:
            message: Debug message
            extra_data: Additional data for context
        """
        function_name = self._get_caller_function_name()
        log_message = f"[DEBUG] [{function_name}] {message}"

        if extra_data:
            log_message += f" | Data: {extra_data}"

        self.logger.debug(log_message)

    def critical(
        self,
        message: str,
        exception: Optional[Exception] = None,
        extra_data: Optional[Dict[str, Any]] = None,
    ):
        """
        Critical log with function name.

        Args:
            message: Critical message
            exception: Caught exception (optional)
            extra_data: Additional data for context
        """
        function_name = self._get_caller_function_name()
        log_message = f"[CRITICAL] [{function_name}] {message}"

        if exception:
            log_message += f" | Exception: {str(exception)}"

        if extra_data:
            log_message += f" | Data: {extra_data}"

        self.logger.critical(log_message)

    # Airflow-specific methods

    def log_task_start(self, task_id: str, dag_id: str):
        """
        Log task start for Airflow tasks.

        Args:
            task_id: Airflow task ID
            dag_id: Airflow DAG ID
        """
        self.info(f"Task started", {"task_id": task_id, "dag_id": dag_id})

    def log_task_success(
        self, task_id: str, dag_id: str, execution_time: Optional[float] = None
    ):
        """
        Log task success for Airflow tasks.

        Args:
            task_id: Airflow task ID
            dag_id: Airflow DAG ID
            execution_time: Task execution time in seconds
        """
        extra_data = {"task_id": task_id, "dag_id": dag_id}
        if execution_time:
            extra_data["execution_time_seconds"] = execution_time

        self.info(f"Task completed successfully", extra_data)

    def log_task_failure(
        self, task_id: str, dag_id: str, exception: Optional[Exception] = None
    ):
        """
        Log task failure for Airflow tasks.

        Args:
            task_id: Airflow task ID
            dag_id: Airflow DAG ID
            exception: Exception that caused the failure
        """
        self.error(
            f"Task failed",
            exception=exception,
            extra_data={"task_id": task_id, "dag_id": dag_id},
        )

    def log_xcom_push(self, key: str, value: Any, task_id: str):
        """
        Log XCom push operation.

        Args:
            key: XCom key
            value: XCom value
            task_id: Task ID pushing the XCom
        """
        self.info(
            f"XCom pushed",
            {"xcom_key": key, "task_id": task_id, "value_type": type(value).__name__},
        )

    def log_xcom_pull(self, key: str, task_id: str, success: bool = True):
        """
        Log XCom pull operation.

        Args:
            key: XCom key
            task_id: Task ID pulling the XCom
            success: Whether the pull was successful
        """
        status = "successful" if success else "failed"
        self.info(f"XCom pull {status}", {"xcom_key": key, "task_id": task_id})

    def log_database_operation(
        self, operation: str, table: str, affected_rows: Optional[int] = None
    ):
        """
        Log database operations.

        Args:
            operation: Type of operation (SELECT, INSERT, UPDATE, DELETE)
            table: Table name
            affected_rows: Number of affected rows
        """
        extra_data = {"operation": operation, "table": table}
        if affected_rows is not None:
            extra_data["affected_rows"] = affected_rows

        self.info(f"Database operation completed", extra_data)

    def log_api_call(
        self, endpoint: str, method: str = "GET", status_code: Optional[int] = None
    ):
        """
        Log API calls.

        Args:
            endpoint: API endpoint
            method: HTTP method
            status_code: HTTP status code
        """
        extra_data = {"endpoint": endpoint, "method": method}
        if status_code:
            extra_data["status_code"] = status_code

        self.info(f"API call made", extra_data)

    def log_file_operation(
        self, operation: str, file_path: str, file_size: Optional[int] = None
    ):
        """
        Log file operations.

        Args:
            operation: Type of operation (read, write, delete, etc.)
            file_path: Path to the file
            file_size: File size in bytes
        """
        extra_data = {"operation": operation, "file_path": file_path}
        if file_size:
            extra_data["file_size_bytes"] = file_size

        self.info(f"File operation completed", extra_data)


# Utility function to create a singleton logger instance
_logger_instance = None


def get_logger(
    name: str = "airflow_custom",
    level: int = logging.INFO,
    log_file: Optional[str] = None,
    include_timestamp: bool = True,
) -> AirflowLogger:
    """
    Get or create a logger instance (singleton pattern).

    Args:
        name: Logger name
        level: Logging level
        log_file: Path to log file (optional)
        include_timestamp: Whether to include timestamp in logs

    Returns:
        AirflowLogger instance
    """
    global _logger_instance

    if _logger_instance is None:
        _logger_instance = AirflowLogger(
            name=name,
            level=level,
            log_file=log_file,
            include_timestamp=include_timestamp,
        )

    return _logger_instance


# Example usage and decorator for automatic logging
def log_function_calls(logger: AirflowLogger):
    """
    Decorator to automatically log function entry and exit.

    Args:
        logger: AirflowLogger instance

    Usage:
        @log_function_calls(logger)
        def my_function():
            pass
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            logger.debug(f"Entering function: {func.__name__}")
            try:
                result = func(*args, **kwargs)
                logger.debug(f"Exiting function: {func.__name__}")
                return result
            except Exception as e:
                logger.error(f"Function {func.__name__} failed", exception=e)
                raise

        return wrapper

    return decorator
