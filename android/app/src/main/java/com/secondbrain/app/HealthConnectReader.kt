package com.secondbrain.app

import android.content.Context
import androidx.health.connect.client.HealthConnectClient
import androidx.health.connect.client.HealthConnectFeatures
import androidx.health.connect.client.permission.HealthPermission
import androidx.health.connect.client.feature.ExperimentalFeatureAvailabilityApi
import androidx.health.connect.client.records.ActiveCaloriesBurnedRecord
import androidx.health.connect.client.records.DistanceRecord
import androidx.health.connect.client.records.HeartRateRecord
import androidx.health.connect.client.records.SleepSessionRecord
import androidx.health.connect.client.records.StepsRecord
import androidx.health.connect.client.records.WeightRecord
import androidx.health.connect.client.request.AggregateRequest
import androidx.health.connect.client.time.TimeRangeFilter
import java.time.LocalDate
import java.time.ZoneId
import kotlin.math.round

data class HealthSample(
    val externalId: String,
    val recordedAt: String,
    val metric: String,
    val value: Double,
    val unit: String,
)

object HealthConnectReader {
    val readPermissions = setOf(
        HealthPermission.getReadPermission(StepsRecord::class),
        HealthPermission.getReadPermission(HeartRateRecord::class),
        HealthPermission.getReadPermission(SleepSessionRecord::class),
        HealthPermission.getReadPermission(WeightRecord::class),
        HealthPermission.getReadPermission(ActiveCaloriesBurnedRecord::class),
        HealthPermission.getReadPermission(DistanceRecord::class),
    )

    fun sdkStatus(context: Context): Int = HealthConnectClient.getSdkStatus(context)

    @OptIn(ExperimentalFeatureAvailabilityApi::class)
    fun backgroundPermission(context: Context): String? {
        if (sdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) return null
        val client = HealthConnectClient.getOrCreate(context)
        return if (client.features.getFeatureStatus(HealthConnectFeatures.FEATURE_READ_HEALTH_DATA_IN_BACKGROUND) == HealthConnectFeatures.FEATURE_STATUS_AVAILABLE) {
            HealthPermission.PERMISSION_READ_HEALTH_DATA_IN_BACKGROUND
        } else null
    }

    suspend fun hasReadPermissions(context: Context): Boolean {
        if (sdkStatus(context) != HealthConnectClient.SDK_AVAILABLE) return false
        return HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions().containsAll(readPermissions)
    }

    suspend fun canReadInBackground(context: Context): Boolean {
        val permission = backgroundPermission(context) ?: return false
        return HealthConnectClient.getOrCreate(context).permissionController.getGrantedPermissions().contains(permission)
    }

    suspend fun recent(context: Context, days: Long = 14): List<HealthSample> {
        check(sdkStatus(context) == HealthConnectClient.SDK_AVAILABLE) { "此手机暂不可用 Health Connect" }
        val client = HealthConnectClient.getOrCreate(context)
        check(client.permissionController.getGrantedPermissions().containsAll(readPermissions)) { "健康数据读取权限尚未全部授权" }
        val zone = ZoneId.systemDefault()
        val today = LocalDate.now(zone)
        val samples = mutableListOf<HealthSample>()
        for (offset in (days - 1) downTo 0) {
            val day = today.minusDays(offset)
            val start = day.atStartOfDay(zone).toInstant()
            val end = day.plusDays(1).atStartOfDay(zone).toInstant().coerceAtMost(java.time.Instant.now())
            if (!end.isAfter(start)) continue
            val result = client.aggregate(
                AggregateRequest(
                    metrics = setOf(
                        StepsRecord.COUNT_TOTAL,
                        HeartRateRecord.BPM_AVG,
                        SleepSessionRecord.SLEEP_DURATION_TOTAL,
                        WeightRecord.WEIGHT_AVG,
                        ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL,
                        DistanceRecord.DISTANCE_TOTAL,
                    ),
                    timeRangeFilter = TimeRangeFilter.between(start, end),
                )
            )
            fun add(metric: String, value: Double?, unit: String) {
                if (value == null || value.isNaN() || value.isInfinite()) return
                samples += HealthSample(
                    externalId = "health-connect:$metric:$day",
                    recordedAt = end.toString(), metric = metric,
                    value = round(value * 100.0) / 100.0, unit = unit,
                )
            }
            add("steps", result[StepsRecord.COUNT_TOTAL]?.toDouble(), "步")
            add("heart_rate", result[HeartRateRecord.BPM_AVG]?.toDouble(), "次/分")
            add("sleep_hours", result[SleepSessionRecord.SLEEP_DURATION_TOTAL]?.toMinutes()?.div(60.0), "小时")
            add("weight", result[WeightRecord.WEIGHT_AVG]?.inKilograms, "kg")
            add("active_energy", result[ActiveCaloriesBurnedRecord.ACTIVE_CALORIES_TOTAL]?.inKilocalories, "千卡")
            add("distance", result[DistanceRecord.DISTANCE_TOTAL]?.inKilometers, "km")
        }
        return samples
    }
}
