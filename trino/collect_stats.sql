-- ALTER TABLE snowflake.salesforce.contact EXECUTE collect_statistics;

SELECT 
  "c_0", 
  "c_1", 
  "c_2", 
  "c_3", 
  "c_4", 
  "c_5", 
  "c_6" 
FROM (
  SELECT 
      -- Metrics for entire table
      CAST(COUNT(1) AS double precision)                                            AS "c_0",
      -- Metrics for column # 1
      CAST(COUNT(DISTINCT("ID")) AS double precision)                               AS "c_1", 
      CAST((SUM(CASE WHEN "ID" IS NULL THEN 1.0 ELSE 0.0 END
  ) / CAST(COUNT(1) AS double precision)) AS double precision)                      AS "c_2", 
      CAST(SUM(CAST(LENGTH("ID") AS double precision)) AS double precision)         AS "c_3", 
      -- Metrics for column # 2
      CAST(COUNT(DISTINCT("OWNER_ID")) AS double precision)                         AS "c_4", 
      CAST((SUM(CASE WHEN "OWNER_ID" IS NULL THEN 1.0 ELSE 0.0 END
  ) / CAST(COUNT(1) AS double precision)) AS double precision)                      AS "c_5", 
      CAST(SUM(CAST(LENGTH("OWNER_ID") AS double precision)) AS double precision)   AS "c_6" 
  FROM 
    "DATA_WAREHOUSE"."SALESFORCE"."CONTACT"
  ) 

