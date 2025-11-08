package api

type TaskReq struct {
	TaskName  string `json:"task_name"`
	TimeOut   int    `json:"time_out"`
	TaskId    string `json:"task_id"`
	SleepTime int    `json:"sleep_time"`
}

type StopTaskReq struct {
	TaskId string `json:"task_id"`
}

type StopServerReq struct {
	Secret string `json:"secret"`
}
