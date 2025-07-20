package results

import (
	"database/sql"
	"lottery/cmd/pkg/db"
	"lottery/pkg/schemas"
	"strconv"

	"github.com/gin-gonic/gin"
	slog "github.com/stainton/logger"
)

func QueryResultsWrapper(logger slog.Logger, d *sql.DB) gin.HandlerFunc {
	return func(ctx *gin.Context) {
		numbers := &schemas.DrawNumbers{}
		if err := ctx.ShouldBindJSON(numbers); err != nil {
			logger.Errorf("解析payload中的中奖结果失败：%+v", err)
			ctx.JSON(400, gin.H{"error": "Invalid input"})
			return
		}
		number, err := strconv.Atoi(numbers.Numbers)
		if err != nil {
			logger.Errorf("中奖结果无法解析为数字：%+v", err)
			ctx.JSON(400, gin.H{"error": "Invalid number format"})
			return
		}

		// 这个只能查询到以方案进行购买的，方案中包含对应数字的订单
		winners, err := db.QueryResults(d, number)
		if err != nil {
			logger.Errorf("查询中奖订单失败：%+v", err)
			ctx.JSON(500, gin.H{"error": "Failed to query results"})
			return
		}
		odrs, err := db.GetOrderWithNumberInScheme(d, numbers.Numbers)
		if err != nil {
			logger.Errorf("直接从orders中查询中奖订单失败：%+v", err)
			ctx.JSON(500, gin.H{"error": "Failed to query results"})
			return
		}
		winners = append(winners, odrs...)
		ctx.JSON(200, winners)
	}
}
