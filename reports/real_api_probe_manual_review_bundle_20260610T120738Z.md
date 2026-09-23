# Real API Probe Manual Review Bundle

- Frozen output root: `outputs/llm_generation_real_api_probe_20260610T120628Z`
- Probe result JSON: `reports/real_api_probe_result_20260610T120628Z.json`
- Existing manual review CSV: `reports/real_api_probe_manual_review_20260610T120628Z.csv`
- Record count: `5`
- mock_only: `False`
- real_generation_pending: `False`

## Review Instructions

This bundle is for human review only. Do not treat automatic checks as human judgment.

Common checks:
- Is the output a single-line commit subject?
- Is it faithful to the diff and original commit message?
- Does it omit any major independent change?
- Does it assert behavior, motive, or effect that the diff does not support?

Category-specific focus:
- `atomic_simple / G1`: check whether the output captures the single main change and does not over-promote supporting tests.
- `hard_b / G1`: check whether complex but single-purpose edits stay compressed into one purpose without fake splitting.
- `synthetic_multi / G4`: check whether both intents are covered and whether retrieval examples appear relevant.
- `synthetic_multi / G5`: compare against G4 for completeness and faithfulness; check whether the model copies the oracle plan mechanically.
- `M_real_multi / G4`: check whether the output over-infers unstated motivation or effect from the diff alone.

Special attention:
- For `Refactor ComponentBase internals and flatten Surface cell storage for ABI stability`, verify whether `for ABI stability` is supported by diff or original message evidence.

## Record 1

- Sample ID: `atomic_simple:eb8a30b8079b8d73`
- Category: `atomic_simple`
- Strategy: `G1`
- Repo: `camunda/zeebe`
- Repo canonical: `camunda/zeebe`
- Repo parse status: `github_slug`
- SHA: `448964457e06c088df68d78cf10cdbcde971530e`
- Generated subject: `Add signal event validation tests`
- Reference subject: `test(engine): added signal events deployment tests`

### Original Commit Message

```text
test(engine): added signal events deployment tests
```

### Prompt Metadata

- Prompt chars: `11800`
- Estimated prompt tokens: `2950`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `912`
- Usage: `{'prompt_tokens': 2993, 'completion_tokens': 5, 'total_tokens': 2998, 'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 2993}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `33`
- Subject length tokens: `5`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java b/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java
new file mode 100644
index 00000000000..9ab7a439801
--- /dev/null
+++ b/engine/src/test/java/io/camunda/zeebe/engine/processing/deployment/model/validation/SignalEventValidationTest.java
@@ -0,0 +1,290 @@
+/*
+ * Copyright Camunda Services GmbH and/or licensed to Camunda Services GmbH under
+ * one or more contributor license agreements. See the NOTICE file distributed
+ * with this work for additional information regarding copyright ownership.
+ * Licensed under the Zeebe Community License 1.1. You may not use this file
+ * except in compliance with the Zeebe Community License 1.1.
+ */
+package io.camunda.zeebe.engine.processing.deployment.model.validation;
+
+import static org.assertj.core.api.Assertions.assertThat;
+
+import io.camunda.zeebe.engine.util.EngineRule;
+import io.camunda.zeebe.model.bpmn.Bpmn;
+import io.camunda.zeebe.model.bpmn.BpmnModelInstance;
+import io.camunda.zeebe.model.bpmn.builder.ProcessBuilder;
+import io.camunda.zeebe.model.bpmn.instance.zeebe.ZeebeTaskDefinition;
+import io.camunda.zeebe.protocol.record.Assertions;
+import io.camunda.zeebe.protocol.record.ExecuteCommandResponseDecoder;
+import io.camunda.zeebe.protocol.record.Record;
+import io.camunda.zeebe.protocol.record.RecordType;
+import io.camunda.zeebe.protocol.record.RejectionType;
+import io.camunda.zeebe.protocol.record.intent.DeploymentIntent;
+import io.camunda.zeebe.protocol.record.value.DeploymentRecordValue;
+import io.camunda.zeebe.test.util.Strings;
+import io.camunda.zeebe.test.util.record.RecordingExporterTestWatcher;
+import org.junit.ClassRule;
+import org.junit.Rule;
+import org.junit.Test;
+
+public final class SignalEventValidationTest {
+
+  @ClassRule public static final EngineRule engine = EngineRule.singlePartition();
+
+  @Rule
+  public final RecordingExporterTestWatcher recordingExporterTestWatcher =
+      new RecordingExporterTestWatcher();
+
+  @Test
+  public void shouldDeploySignalStartEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId).startEvent("start").signal("signalName").done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal start event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalEndEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent("start")
+            .endEvent()
+            .addExtensionElement(ZeebeTaskDefinition.class, b -> b.setType("type"))
+            .signalEventDefinition()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal end event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalThrowEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent("start")
+            .intermediateThrowEvent()
+            .addExtensionElement(ZeebeTaskDefinition.class, b -> b.setType("signalType"))
+            .signalEventDefinition()
+            .throwEventDefinitionDone()
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal throw event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeployMultipleSignalStartEvents() {
+    // given
+    final BpmnModelInstance processDefinition = processWithMultipleSignalStartEvents();
+
+    // when
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support multiple signal star event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalBoundaryEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .manualTask()
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalStartAndMultipleBoundaryEvents() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .signal("start-signal")
+            .manualTask("task")
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName1")))
+            .endEvent()
+            .moveToActivity("task")
+            .boundaryEvent("boundary-2", b -> b.signal(m -> m.name("signalName2")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support signal start event and multiple signal boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeployEventSubProcessWithMultipleSignalEvents() {
+    // given
+    final BpmnModelInstance processDefinition =
+        getEventSubProcessWithEmbeddedSubProcessWithBoundarySignalEvent();
+
+    // when
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support event sub process with signal start event and boundary event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalIntermediateCatchEvent() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .intermediateCatchEvent("foo")
+            .signal("signalName")
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs("Support signal intermediate catch event process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldDeploySignalStartAndBoundaryEventEvenWithSameSignal() {
+    // given
+    final String processId = Strings.newRandomValidBpmnId();
+
+    // when
+    final BpmnModelInstance processDefinition =
+        Bpmn.createExecutableProcess(processId)
+            .startEvent()
+            .signal(m -> m.id("start-signal").name("signalName"))
+            .manualTask()
+            .boundaryEvent("boundary-1", b -> b.signal(m -> m.name("signalName")))
+            .endEvent()
+            .done();
+
+    final Record<DeploymentRecordValue> deployment =
+        engine.deployment().withXmlResource(processDefinition).deploy();
+
+    // then
+    assertThat(deployment.getKey())
+        .describedAs(
+            "Support signal start and boundary event even with the same signal name process deployment")
+        .isNotNegative();
+  }
+
+  @Test
+  public void shouldRejectDeployMultipleStartEventsWithSameSignal() {
+    // given
+    final BpmnModelInstance processDefinition = getProcessWithMultipleStartEventsWithSameSignal();
+
+    final Record<DeploymentRecordValue> rejectedDeployment =
+        engine.deployment().withXmlResource(processDefinition).expectRejection().deploy();
+
+    // then
+    Assertions.assertThat(rejectedDeployment)
+        .hasKey(ExecuteCommandResponseDecoder.keyNullValue())
+        .hasRecordType(RecordType.COMMAND_REJECTION)
+        .hasIntent(DeploymentIntent.CREATE)
+        .hasRejectionType(RejectionType.INVALID_ARGUMENT);
+    assertThat(rejectedDeployment.getRejectionReason())
+        .contains("Element: process")
+        .contains(
+            "ERROR: Multiple signal event definitions with the same name 'signalName' are not allowed.");
+  }
+
+  private static BpmnModelInstance
+      getEventSubProcessWithEmbeddedSubProcessWithBoundarySignalEvent() {
+    final ProcessBuilder builder = Bpmn.createExecutableProcess("process");
+    builder
+        .eventSubProcess("event_sub_proc")
+        .startEvent(
+            "event_sub_start",
+            a -> a.signal(m -> m.id("event_sub_start_signal").name("signalName1")))
+        .subProcess(
+            "embedded",
+            s ->
+                s.boundaryEvent(
+                    "boundary-msg", b -> b.signal("signalName2").endEvent("boundary-end")))
+        .embeddedSubProcess()
+        .startEvent("embedded_sub_start")
+        .endEvent("embedded_sub_end")
+        .moveToNode("embedded")
+        .endEvent("event_sub_end");
+    return builder.startEvent("start").endEvent("end").done();
+  }
+
+  public static BpmnModelInstance processWithMultipleSignalStartEvents() {
+    final ProcessBuilder process = Bpmn.createExecutableProcess();
+    process.startEvent().signal("s1").endEvent();
+    process.startEvent().signal("s2").endEvent();
+    process.startEvent().signal(s -> s.nameExpression("signal_var")).endEvent();
+    return process.startEvent().signal("s3").endEvent().done();
+  }
+
+  private static BpmnModelInstance getProcessWithMultipleStartEventsWithSameSignal() {
+    final ProcessBuilder process = Bpmn.createExecutableProcess("processId");
+    final String signalName = "signalName";
+    process.startEvent("start1").signal(m -> m.id("start-signal").name(signalName)).endEvent();
+    process.startEvent("start2").signal(signalName).endEvent();
+    return process.done();
+  }
+}
```

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it accurately express one main change?
- Does it incorrectly elevate supporting test edits into the main goal?

## Record 2

- Sample ID: `hard_b:3366abdb796ceefc`
- Category: `hard_b`
- Strategy: `G1`
- Repo: `mongodb/mongoid`
- Repo canonical: `mongodb/mongoid`
- Repo parse status: `github_slug`
- SHA: `73c3afdf131235b89e4e73ce87b4640ead9cad88`
- Generated subject: `Implement $lookup-based eager loading for associations`
- Reference subject: `MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)`

### Original Commit Message

```text
MONGOID 5731 Add Criteria#eager_load method to use aggregation pipeline for eager loading (#6081)

* Adds support for single hash input in nested attributes for has_many associations.

* Using $lookup for #eager_load

* add a forgotten comment

* removing unneeded check

* removing accidental change

* updating comment

* switching to only one query

* removing debugging

* Cleaning up code

* removing bug

* Switch how we approach querying to fix pipeline

* adding tests for to_pipeline_for_lookup

* Adding testing, including testing correct # of queries

* adding argument error

* Fixing error messages for eager_load

* adding @use_lookup to marshalable and criteria copy

* About to remove a lot of this - commit in case I decide this functionality actually is needed

* We no longer do lookup on embedded docs

* re-adding removed test

* using preload_for_lookup instead of preload

* Fixing marshalling errors

* moving private function to end of class

* Adding tests and trying to fix bugs shown by them

* Fixing bug with primary_key

* Only test on 5.0 and above

* Responding to automatic comments - trying to make code more readable

* adding buildable tests

* Adding benchmarking

* Removing default sort

* Addressing comments

* Fixing first() to allow nil, and adding default ordering
```

### Prompt Metadata

- Prompt chars: `72638`
- Estimated prompt tokens: `18159`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `2070`
- Usage: `{'prompt_tokens': 20648, 'completion_tokens': 9, 'total_tokens': 20657, 'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 20648}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `54`
- Subject length tokens: `7`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `True`
```diff
diff --git a/lib/mongoid/association/accessors.rb b/lib/mongoid/association/accessors.rb
--- a/lib/mongoid/association/accessors.rb
+++ b/lib/mongoid/association/accessors.rb
@@ -131,6 +131,10 @@ def get_relation(name, association, object, reload = false)
+              # Check if data was loaded via $lookup aggregation
+              elsif !association.embedded? && attributes.key?(name.to_s)
+                # Use the pre-loaded association data from $lookup
+                __build__(name, attributes[name.to_s], association)
@@ -223,7 +227,7 @@ def _mongoid_filter_selected_fields(assoc_key)
-            object._id == attributes[association.key]
+            object[association.try(:primary_key) || :_id] == attributes[association.key]
diff --git a/lib/mongoid/association/eager.rb b/lib/mongoid/association/eager.rb
--- a/lib/mongoid/association/eager.rb
+++ b/lib/mongoid/association/eager.rb
@@ -14,12 +14,18 @@ class Eager
+      # @param [ Boolean ] use_lookup Whether to use $lookup aggregation
+      #   for eager loading. This is used in Criteria#eager_load.
+      # @param [ Array<Hash> ] pipeline The aggregation pipeline to use
+      #   when using $lookup for eager loading.
-      def initialize(associations, docs)
+      def initialize(associations, docs, use_lookup = false, pipeline = [])
+        @use_lookup = use_lookup
+        @pipeline = pipeline
@@ -30,6 +36,13 @@ def initialize(associations, docs)
+
+        if @use_lookup
+          preload_with_lookup
+          @loaded = @docs
+          return @loaded.flatten
+        end
+
@@ -49,6 +62,21 @@ def preload
+      # Preload the current association using $lookup aggregation.
+      # This method executes the aggregation pipeline
+      # and instantiates the documents.
+      # @example Preload the current association using $lookup.
+      #   loader.preload_with_lookup
+      def preload_with_lookup
+        # For $lookup aggregation, execute pipeline and instantiate documents
+        owner_class = @associations.first.owner_class
+        aggregated_docs = owner_class.collection.aggregate(@pipeline)
+        aggregated_docs.each do |doc|
+          parsed_doc = Factory.from_db(owner_class, doc)
+          @docs << parsed_doc
+        end
+      end
+
@@ -69,10 +97,7 @@ def each_loaded_document(&block)
-        criteria = cls.criteria
-        criteria = criteria.apply_scope(@association.scope)
-        criteria = criteria.any_in(key => keys)
-        criteria.inclusions = criteria.inclusions - [@association]
+        criteria = prepare_criteria_for_loaded_documents(cls, keys)
@@ -155,6 +180,19 @@ def set_relation(doc, element)
+
+      # Prepares the criteria to retrieve the documents of the specified
+      # class, that have the foreign key included in the specified list of keys.
+      # When the documents are retrieved, the set of inclusions applied
+      # is the set of inclusions applied to the host document minus the
+      # association that is being eagerly loaded.
+      def prepare_criteria_for_loaded_documents(cls, keys)
+        criteria = cls.criteria
+        criteria = criteria.apply_scope(@association.scope)
+        criteria = criteria.any_in(key => keys)
+        criteria.inclusions = criteria.inclusions - [@association]
+        criteria
+      end
diff --git a/lib/mongoid/association/eager_loadable.rb b/lib/mongoid/association/eager_loadable.rb
--- a/lib/mongoid/association/eager_loadable.rb
+++ b/lib/mongoid/association/eager_loadable.rb
@@ -30,6 +30,13 @@ def eager_load(docs)
+      # Load the associations for the given documents using $lookup.
+      #
+      # @return [ Array<Mongoid::Document> ] The given documents.
+      def eager_load_with_lookup
+        preload_for_lookup(criteria)
+      end
+
@@ -66,6 +73,97 @@ def preload(associations, docs)
+
+      # Load the associations for the given documents. This will be done
+      # recursively to load the associations of the given documents'
+      # associated documents.
+      #
+      # @param [ Array<Mongoid::Association::Relatable> ] associations
+      #   The associations to load.
+      # @param [ Array<Mongoid::Document> ] docs The documents.
+      def preload_for_lookup(criteria)
+        assoc_map = criteria.inclusions.group_by(&:inverse_class_name)
+
+        # match first
+        pipeline = criteria.selector.to_pipeline
+        # then sort, skip, limit
+        pipeline.concat(criteria.options.to_pipeline_for_lookup)
+
+        # account for single-collection inheritance
+        root_class = klass.root_class
+
+        if assoc_map[klass.to_s]
+          assoc_map[klass.to_s].each do |assoc|
+            # Create a copy of the mapping for each top-level association to avoid mutation issues
+            pipeline << create_pipeline(assoc, assoc_map.dup)
+          end
+        end
+
+        if klass != root_class && assoc_map[root_class.to_s]
+          assoc_map[root_class.to_s].each do |assoc|
+            # Create a copy of the mapping for each top-level association to avoid mutation issues
+            pipeline << create_pipeline(assoc, assoc_map.dup)
+          end
+        end
+
+        Eager.new(criteria.inclusions, [], true, pipeline).run
+      end
+
+      def switch_local_and_foreign_fields?(association)
+        association.is_a?(Mongoid::Association::Referenced::BelongsTo) ||
+          association.is_a?(Mongoid::Association::Referenced::HasAndBelongsToMany)
+      end
+
+      def create_pipeline(current_assoc, mapping)
+        # Build nested pipeline for children and ordering
+        pipeline_stages = []
+
+        # For belongs_to and has_and_belongs_to_many, the foreign key is on the current document
+        # For has_many/has_one, the foreign key is on the related document
+        if switch_local_and_foreign_fields?(current_assoc)
+          local_field = current_assoc.foreign_key
+          foreign_field = current_assoc.primary_key
+        else
+          local_field = current_assoc.primary_key
+          foreign_field = current_assoc.foreign_key
+        end
+        
+        # Build the 'as' field with embedded path prefix if needed
+        as_field = current_assoc.name.to_s
+        
+        stage = {
+          "$lookup" => {
+            "from" => current_assoc.klass.collection.name,
+            "localField" => local_field,
+            "foreignField" => foreign_field,
+            "as" => as_field
+          }
+        }
+        
+        # Add ordering if defined on the association, or default to _id for consistent order
+        if current_assoc.order
+          sort_spec = current_assoc.order.is_a?(Hash) ? current_assoc.order : { current_assoc.order => 1 }
+          pipeline_stages << { "$sort" => sort_spec }
+        else
+          # Default to sorting by _id to maintain insertion order consistency
+          pipeline_stages << { "$sort" => { "_id" => 1 } }
+        end
+        
+        # Add nested lookups for child associations
+        # Child associations don't need the embedded_path prefix since they're referenced from the looked-up document
+        # Remove this class from the mapping to prevent infinite loops with circular references
+        class_name = current_assoc.klass.to_s
+        if child_assocs = mapping.delete(class_name)
+          child_assocs.each do |child|
+            pipeline_stages << create_pipeline(child, mapping)
+          end
+        end
+        
+        # Always add pipeline since we always have at least $sort
+        stage["$lookup"]["pipeline"] = pipeline_stages
+        
+        stage
+      end
diff --git a/lib/mongoid/association/embedded/embedded_in/proxy.rb b/lib/mongoid/association/embedded/embedded_in/proxy.rb
--- a/lib/mongoid/association/embedded/embedded_in/proxy.rb
+++ b/lib/mongoid/association/embedded/embedded_in/proxy.rb
@@ -90,6 +90,8 @@ class << self
+            # @param [ true | false ] use_lookup Whether to use a $lookup
+            #   aggregation stage to perform the eager load.
diff --git a/lib/mongoid/association/referenced/belongs_to/buildable.rb b/lib/mongoid/association/referenced/belongs_to/buildable.rb
--- a/lib/mongoid/association/referenced/belongs_to/buildable.rb
+++ b/lib/mongoid/association/referenced/belongs_to/buildable.rb
@@ -23,6 +23,22 @@ module Buildable
+            
+            # Handle array from $lookup aggregation (returns array even for belongs_to)
+            if object.is_a?(Array)
+              first = object.first
+              case first
+              when nil, Mongoid::Document then return first
+              when Hash then return Factory.execute_from_db(klass, first, nil, selected_fields, execute_callbacks: false)
+              else raise ArgumentError, "Cannot build belongs_to association from array"
+              end
+            end
+            
+            # Handle single hash from $lookup with $unwind
+            if object.is_a?(Hash)
+              return Factory.execute_from_db(klass, object, nil, selected_fields, execute_callbacks: false)
+            end
+
diff --git a/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb b/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
--- a/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
+++ b/lib/mongoid/association/referenced/has_and_belongs_to_many/buildable.rb
@@ -23,6 +23,11 @@ module Buildable
+              # Handle array of hashes from $lookup aggregation
+              if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+                return object.map { |attrs| Factory.execute_from_db(klass, attrs, nil, selected_fields, execute_callbacks: false) }
+              end
+              
diff --git a/lib/mongoid/association/referenced/has_many/buildable.rb b/lib/mongoid/association/referenced/has_many/buildable.rb
--- a/lib/mongoid/association/referenced/has_many/buildable.rb
+++ b/lib/mongoid/association/referenced/has_many/buildable.rb
@@ -23,6 +23,12 @@ module Buildable
+            
+            # Handle array of hashes from $lookup aggregation
+            if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+              return object.map { |attrs| Factory.execute_from_db(klass, attrs, nil, selected_fields, execute_callbacks: false) }
+            end
+            
diff --git a/lib/mongoid/association/referenced/has_one/buildable.rb b/lib/mongoid/association/referenced/has_one/buildable.rb
--- a/lib/mongoid/association/referenced/has_one/buildable.rb
+++ b/lib/mongoid/association/referenced/has_one/buildable.rb
@@ -24,6 +24,12 @@ module Buildable
+              # Handle array of hashes from $lookup aggregation
+              if object.is_a?(Array) && object.all? { |o| o.is_a?(Hash) }
+                doc = object.first
+                return doc ? Factory.execute_from_db(klass, doc, nil, selected_fields, execute_callbacks: false) : nil
+              end
+              
diff --git a/lib/mongoid/association/relatable.rb b/lib/mongoid/association/relatable.rb
--- a/lib/mongoid/association/relatable.rb
+++ b/lib/mongoid/association/relatable.rb
@@ -37,6 +37,11 @@ module Relatable
+      # The class that owns this association.
+      #
+      # @return [ Class ] The owner class.
+      attr_reader :owner_class
+
diff --git a/lib/mongoid/contextual/memory.rb b/lib/mongoid/contextual/memory.rb
--- a/lib/mongoid/contextual/memory.rb
+++ b/lib/mongoid/contextual/memory.rb
@@ -141,11 +141,16 @@ def exists?(id_or_conditions = :none)
-        if limit
-          eager_load(documents.first(limit))
+        use_first = limit.nil?
+        limit ||= 1
+        if criteria.use_lookup?
+          @criteria = criteria.limit(limit)
+          result = eager_load_with_lookup()
-          eager_load([documents.first]).first
+          result = eager_load(documents.first(limit))
+
+        use_first ? result.first : result
@@ -530,7 +535,7 @@ def third_to_last!
-          eager_load(docs)
+          criteria.use_lookup? ? ea
... [excerpt truncated]
```

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it keep this complex but single-purpose change compressed into one purpose?
- Does it over-segment supporting edits into fake multiple goals?

## Record 3

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G4`
- Repo: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Repo parse status: `github_slug`
- SHA: `2b5a8ddc4845d31052de779035030032c6a75b9b`
- Generated subject: `Add unsafe comparison and improve docs page generation`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Prompt Metadata

- Prompt chars: `8329`
- Estimated prompt tokens: `2082`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `1179`
- Usage: `{'prompt_tokens': 2431, 'completion_tokens': 8, 'total_tokens': 2439, 'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 2431}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `54`
- Subject length tokens: `8`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
index 29d9558a..3d9a70e0 100644
--- a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
+++ b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
@@ -1,23 +1,74 @@
-import { USD } from '@dinero.js/currencies';
-import { dinero, greaterThanOrEqual } from '../../..';
+import { USD, EUR } from '@dinero.js/currencies';
+import { dinero, greaterThanOrEqual, unsafeGreaterThanOrEqual } from '../../..';
 
 describe('greaterThanOrEqual', () => {
-  it('returns false when the first amount is less than the other', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 800, currency: USD });
+  describe('safe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(false);
-  });
-  it('returns true when amounts are equal', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+      expect(greaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('normalizes the result to the highest scale', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('throws when using different currencies', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => {
+        greaterThanOrEqual(d1, d2);
+      }).toThrowErrorMatchingInlineSnapshot(
+        `"Dinero objects don't have the same currency."`
+      );
+    });
   });
-  it('returns true when the first amount is greater than the other', () => {
-    const d1 = dinero({ amount: 800, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+  describe('unsafe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it("doesn't normalize the result to the highest scale, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it("doesn't throw when using different currencies, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => unsafeGreaterThanOrEqual(d1, d2)).not.toThrow();
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
   });
 });
diff --git a/website/pages/docs/[[...slug]].tsx b/website/pages/docs/[[...slug]].tsx
index 909aa63e..d83ec27c 100644
--- a/website/pages/docs/[[...slug]].tsx
+++ b/website/pages/docs/[[...slug]].tsx
@@ -50,17 +50,15 @@ export const getStaticProps: GetStaticProps = async ({ params }) => {
 
 export const getStaticPaths: GetStaticPaths = async () => {
   const pages = await getFiles('docs');
-  const slugs = pages.map((page) =>
-    page.replace('.mdx', '').split('/').filter(Boolean)
-  );
+  const paths = pages.map((page) => {
+    const slug = page.replace('.mdx', '').split('/').filter(Boolean);
+    const [root] = slug;
 
-  return {
-    paths: slugs
-      .map((slug) => {
-        const [root] = slug;
+    return { params: { slug: root === 'index' ? [] : slug } }
+  });
 
-        return { params: { slug: root === 'index' ? [] : slug } }
-      }),
-    fallback: true,
+  return {
+    paths,
+    fallback: false,
   };
 };
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:c933ca035f67b397', 'ex:4c1cf10f12621101', 'ex:bf55c32e98b37edd']`
- Similarity scores: `[0.2043603498171054, 0.08288081874610767, 0.07646847192943107]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `True`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Exemplar `ex:c933ca035f67b397`
  - Repo/SHA: `holdenk/spark-testing-base` / `d5bfe78e88d2ad8c8c26702c4e793e563263ad8d`
  - Repo canonical: `holdenk/spark-testing-base`
  - Subject: `fix: [~] row comparer & add list aprox comparer (#415)`
  - Similarity score: `0.2043603498171054`
  - Diff summary: `diff --git a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
index f13d92ef..4bca233b 100644
--- a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
+++ b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
@@ -436,6 +436,45 @@ object DataFrameSuiteBase {
   def approxEquals(r1: Row, r2: Row, tolTimestamp: Duration): Boolean =
     approxEquals(r1, r2, 0, tolTimestamp)
 
+  private def compareTimestamp(t1: Timestamp, t2: Timestamp,
+                               tolTimestamp: Duration): Boolean = {
+    !(Duration.between(t1.toInstant, t2.toInstant).abs.compareTo(tolTimestamp) > 0)
+  }`
- Exemplar `ex:4c1cf10f12621101`
  - Repo/SHA: `ccxt/ccxt` / `7c9929931a92bfa9cf565ce2e03391a18631de93`
  - Repo canonical: `ccxt/ccxt`
  - Subject: `refactor: bigone add parsecurrency (#28642)`
  - Similarity score: `0.08288081874610767`
  - Diff summary: `diff --git a/ts/src/bigone.ts b/ts/src/bigone.ts
index 3877038fbb0de..c073d61299819 100644
--- a/ts/src/bigone.ts
+++ b/ts/src/bigone.ts
@@ -523,85 +523,84 @@ export default class bigone extends Exchange {
         // }
         //
         const currenciesData = this.safeList (data, 'data', []);
-        const result: Dict = {};
-        for (let i = 0; i < currenciesData.length; i++) {
-            const currency = currenciesData[i];
-            const id = this.safeString (currency, 'symbol');`
- Exemplar `ex:bf55c32e98b37edd`
  - Repo/SHA: `stacks-network/stacks-core` / `378fc1b80e161ce1b82cc98b3802565222100816`
  - Repo canonical: `stacks-network/stacks-core`
  - Subject: `fix: update changelog for 2.05.0.4.0 and add stx-balance test`
  - Similarity score: `0.07646847192943107`
  - Diff summary: `diff --git a/src/vm/tests/assets.rs b/src/vm/tests/assets.rs
index 617f5b23af..85c716515d 100644
--- a/src/vm/tests/assets.rs
+++ b/src/vm/tests/assets.rs
@@ -106,6 +106,7 @@ fn execute_transaction(env: &mut OwnedEnvironment, issuer: Value, contract_ident
 fn test_native_stx_ops(owned_env: &mut OwnedEnvironment) {
     let contract = "(define-public (burn-stx (amount uint) (p principal)) (stx-burn? amount p))
                     (define-public (xfer-stx (amount uint) (p principal) (t principal)) (stx-transfer? amount p t))
+                    (define-public (balance-stx (p principal)) (stx-balance? p))
                     (define-public (to-contract (amount uint) (p principal))
                       (let ((contract-principal (as-contract tx-sender)))
                         (stx-transfer? amount p contract-principal)))`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it cover both independent intents?
- Does it omit the secondary but still independent intent?
- Do the retrieved examples appear relevant, or does the output mechanically copy them?

## Record 4

- Sample ID: `synthetic_multi:badb1a0475c1b9b1`
- Category: `synthetic_multi`
- Strategy: `G5`
- Repo: `dinerojs/dinero.js`
- Repo canonical: `dinerojs/dinero.js`
- Repo parse status: `github_slug`
- SHA: `2b5a8ddc4845d31052de779035030032c6a75b9b`
- Generated subject: `Add tests for greaterThanOrEqual and fix docs path generation`
- Reference subject: `fix: correct doc paths and test greaterThanOrEqual`

### Original Commit Message

```text
fix: correct doc paths and test greaterThanOrEqual
```

### Prompt Metadata

- Prompt chars: `8727`
- Estimated prompt tokens: `2181`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `1112`
- Usage: `{'prompt_tokens': 2522, 'completion_tokens': 12, 'total_tokens': 2534, 'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 2522}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `61`
- Subject length tokens: `9`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `False`
```diff
diff --git a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
index 29d9558a..3d9a70e0 100644
--- a/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
+++ b/packages/dinero.js/src/api/__tests__/greaterThanOrEqual.test.ts
@@ -1,23 +1,74 @@
-import { USD } from '@dinero.js/currencies';
-import { dinero, greaterThanOrEqual } from '../../..';
+import { USD, EUR } from '@dinero.js/currencies';
+import { dinero, greaterThanOrEqual, unsafeGreaterThanOrEqual } from '../../..';
 
 describe('greaterThanOrEqual', () => {
-  it('returns false when the first amount is less than the other', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 800, currency: USD });
+  describe('safe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(false);
-  });
-  it('returns true when amounts are equal', () => {
-    const d1 = dinero({ amount: 500, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+      expect(greaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('normalizes the result to the highest scale', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(greaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('throws when using different currencies', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => {
+        greaterThanOrEqual(d1, d2);
+      }).toThrowErrorMatchingInlineSnapshot(
+        `"Dinero objects don't have the same currency."`
+      );
+    });
   });
-  it('returns true when the first amount is greater than the other', () => {
-    const d1 = dinero({ amount: 800, currency: USD });
-    const d2 = dinero({ amount: 500, currency: USD });
+  describe('unsafe', () => {
+    it('returns false when the first amount is less than the other', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 800, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it('returns true when amounts are equal', () => {
+      const d1 = dinero({ amount: 500, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it('returns true when the first amount is greater than the other', () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: USD });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
+    it("doesn't normalize the result to the highest scale, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 5000, currency: USD, scale: 3 });
+
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(false);
+    });
+    it("doesn't throw when using different currencies, resulting in an incorrect comparison", () => {
+      const d1 = dinero({ amount: 800, currency: USD });
+      const d2 = dinero({ amount: 500, currency: EUR });
 
-    expect(greaterThanOrEqual(d1, d2)).toBe(true);
+      expect(() => unsafeGreaterThanOrEqual(d1, d2)).not.toThrow();
+      expect(unsafeGreaterThanOrEqual(d1, d2)).toBe(true);
+    });
   });
 });
diff --git a/website/pages/docs/[[...slug]].tsx b/website/pages/docs/[[...slug]].tsx
index 909aa63e..d83ec27c 100644
--- a/website/pages/docs/[[...slug]].tsx
+++ b/website/pages/docs/[[...slug]].tsx
@@ -50,17 +50,15 @@ export const getStaticProps: GetStaticProps = async ({ params }) => {
 
 export const getStaticPaths: GetStaticPaths = async () => {
   const pages = await getFiles('docs');
-  const slugs = pages.map((page) =>
-    page.replace('.mdx', '').split('/').filter(Boolean)
-  );
+  const paths = pages.map((page) => {
+    const slug = page.replace('.mdx', '').split('/').filter(Boolean);
+    const [root] = slug;
 
-  return {
-    paths: slugs
-      .map((slug) => {
-        const [root] = slug;
+    return { params: { slug: root === 'index' ? [] : slug } }
+  });
 
-        return { params: { slug: root === 'index' ? [] : slug } }
-      }),
-    fallback: true,
+  return {
+    paths,
+    fallback: false,
   };
 };
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:c933ca035f67b397', 'ex:4c1cf10f12621101', 'ex:bf55c32e98b37edd']`
- Similarity scores: `[0.2043603498171054, 0.08288081874610767, 0.07646847192943107]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `True`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Exemplar `ex:c933ca035f67b397`
  - Repo/SHA: `holdenk/spark-testing-base` / `d5bfe78e88d2ad8c8c26702c4e793e563263ad8d`
  - Repo canonical: `holdenk/spark-testing-base`
  - Subject: `fix: [~] row comparer & add list aprox comparer (#415)`
  - Similarity score: `0.2043603498171054`
  - Diff summary: `diff --git a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
index f13d92ef..4bca233b 100644
--- a/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
+++ b/core/src/main/2.0/scala/com/holdenkarau/spark/testing/DataFrameSuiteBase.scala
@@ -436,6 +436,45 @@ object DataFrameSuiteBase {
   def approxEquals(r1: Row, r2: Row, tolTimestamp: Duration): Boolean =
     approxEquals(r1, r2, 0, tolTimestamp)
 
+  private def compareTimestamp(t1: Timestamp, t2: Timestamp,
+                               tolTimestamp: Duration): Boolean = {
+    !(Duration.between(t1.toInstant, t2.toInstant).abs.compareTo(tolTimestamp) > 0)
+  }`
- Exemplar `ex:4c1cf10f12621101`
  - Repo/SHA: `ccxt/ccxt` / `7c9929931a92bfa9cf565ce2e03391a18631de93`
  - Repo canonical: `ccxt/ccxt`
  - Subject: `refactor: bigone add parsecurrency (#28642)`
  - Similarity score: `0.08288081874610767`
  - Diff summary: `diff --git a/ts/src/bigone.ts b/ts/src/bigone.ts
index 3877038fbb0de..c073d61299819 100644
--- a/ts/src/bigone.ts
+++ b/ts/src/bigone.ts
@@ -523,85 +523,84 @@ export default class bigone extends Exchange {
         // }
         //
         const currenciesData = this.safeList (data, 'data', []);
-        const result: Dict = {};
-        for (let i = 0; i < currenciesData.length; i++) {
-            const currency = currenciesData[i];
-            const id = this.safeString (currency, 'symbol');`
- Exemplar `ex:bf55c32e98b37edd`
  - Repo/SHA: `stacks-network/stacks-core` / `378fc1b80e161ce1b82cc98b3802565222100816`
  - Repo canonical: `stacks-network/stacks-core`
  - Subject: `fix: update changelog for 2.05.0.4.0 and add stx-balance test`
  - Similarity score: `0.07646847192943107`
  - Diff summary: `diff --git a/src/vm/tests/assets.rs b/src/vm/tests/assets.rs
index 617f5b23af..85c716515d 100644
--- a/src/vm/tests/assets.rs
+++ b/src/vm/tests/assets.rs
@@ -106,6 +106,7 @@ fn execute_transaction(env: &mut OwnedEnvironment, issuer: Value, contract_ident
 fn test_native_stx_ops(owned_env: &mut OwnedEnvironment) {
     let contract = "(define-public (burn-stx (amount uint) (p principal)) (stx-burn? amount p))
                     (define-public (xfer-stx (amount uint) (p principal) (t principal)) (stx-transfer? amount p t))
+                    (define-public (balance-stx (p principal)) (stx-balance? p))
                     (define-public (to-contract (amount uint) (p principal))
                       (let ((contract-principal (as-contract tx-sender)))
                         (stx-transfer? amount p contract-principal)))`

### Oracle Intent Plan

- Oracle intent count: `2`
- Oracle intent subjects: `['fix: fix how paths are passed', 'test: add missing tests for greaterThanOrEqual function']`
- Oracle edit-to-intent: `{'h0': 1, 'h1': 0}`
- Supporting edit note: `Use the structure as evidence. Do not copy the plan mechanically.`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Is it more complete than the G4 output for the same sample?
- Is it more faithful than the G4 output for the same sample?
- Does it mechanically copy the oracle plan?
- Does the oracle plan skew the emphasis away from the actual diff?

## Record 5

- Sample ID: `M_real_multi:f27dfc62b60e1074`
- Category: `M_real_multi`
- Strategy: `G4`
- Repo: `alirezarezvani/claude-skills`
- Repo canonical: `alirezarezvani/claude-skills`
- Repo parse status: `github_slug`
- SHA: `5c539e30dfd8a00153407a763a2d4c86e923b7b5`
- Generated subject: `Add engineering agent orchestrators and Mistral Vibe support`
- Reference subject: `docs(vibe): run /update-docs sync pipeline for Mistral Vibe integration`

### Original Commit Message

```text
docs(vibe): run /update-docs sync pipeline for Mistral Vibe integration

Mirrors the Hermes integration's documentation footprint across the
generated docs site and the marketplace manifest. Also picks up a few
post-v2.8.1 doc-generator outputs that hadn't been committed.

Changes:
- .claude-plugin/marketplace.json — Mistral Vibe added to platform
  compatibility tagline (12 → 13 tools).
- mkdocs.yml — site_description updated 12 → 13 AI coding tools, all 13
  named explicitly (Claude Code · Codex · Gemini · Hermes · Mistral Vibe
  · OpenClaw · Cursor · Aider · Windsurf · Kilo Code · OpenCode ·
  Augment · Antigravity).
- docs/index.md — description meta updated, two install-tab references
  added (Mistral Vibe tab + Mistral Vibe in install tools list),
  stale "12 AI coding tools" → "13" stat card.
- docs/getting-started.md — description meta updated, Mistral Vibe
  install tab added with --domain / --copy / --dry-run / --target flags.
- docs/integrations.md — Mistral Vibe card added to landing grid; new
  full Mistral Vibe section (~130 lines) parallel to the Hermes
  section: discovery paths, install steps, "what works" matrix, verify
  + update + troubleshooting blocks. Scoped to facts verifiable from
  the official Vibe docs.
- docs/agents/, docs/commands/, docs/skills/engineering-team/senior-* —
  regenerated by scripts/generate-docs.py (picks up v2.8.1 senior-*
  engineering skill upgrades that hadn't been re-generated yet).

Verification:
- python3 -m mkdocs build → PASS (20.56s, 513 HTML pages)
- Count consistency across README / CHANGELOG / marketplace / docs/* /
  mkdocs.yml → all read "13 AI coding tools" after fixing one stale
  "12" in docs/index.md
- scripts/sync-vibe-skills.py --help → exits 0
- bash -n scripts/vibe-install.sh → syntax OK
```

### Prompt Metadata

- Prompt chars: `84416`
- Estimated prompt tokens: `21104`
- Status: `generated`
- Thinking mode: `disabled`
- Latency ms: `1569`
- Usage: `{'prompt_tokens': 23558, 'completion_tokens': 11, 'total_tokens': 23569, 'prompt_tokens_details': {'cached_tokens': 0}, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 23558}`

### Automatic Format Checks

- Non-empty: `True`
- Single line: `True`
- Subject length chars: `60`
- Subject length tokens: `8`
- Artifact markers present: `False`

### Diff Excerpt

- Excerpted: `True`
```diff
diff --git a/.claude-plugin/marketplace.json b/.claude-plugin/marketplace.json
--- a/.claude-plugin/marketplace.json
+++ b/.claude-plugin/marketplace.json
@@ -8,7 +8,7 @@
-    "description": "328 production-ready skill packages across 14 domains (engineering, marketing, product, c-level, project management, RA/QM, business growth, finance, productivity, marketing (top-level), research, business-operations [v2.8.0], commercial [v2.8.0], plus standards). ~441 Python tools, ~594 reference guides, 48+ agents (cs-* + personas), 77+ slash commands. v2.8.0 adds 2 new top-level domains (business-operations + commercial) with 15 new skills, context: fork chaining via Matt Pocock grill-with-docs discipline. v2.7.3 adds AEO + security-guidance PreToolUse hook. Compatible with Claude Code, Codex CLI, Gemini CLI, Cursor, OpenClaw, Hermes Agent, and 6 more coding agents.",
+    "description": "328 production-ready skill packages across 14 domains (engineering, marketing, product, c-level, project management, RA/QM, business growth, finance, productivity, marketing (top-level), research, business-operations [v2.8.0], commercial [v2.8.0], plus standards). ~441 Python tools, ~594 reference guides, 48+ agents (cs-* + personas), 77+ slash commands. v2.8.0 adds 2 new top-level domains (business-operations + commercial) with 15 new skills, context: fork chaining via Matt Pocock grill-with-docs discipline. v2.7.3 adds AEO + security-guidance PreToolUse hook. Compatible with Claude Code, Codex CLI, Gemini CLI, Cursor, OpenClaw, Hermes Agent, Mistral Vibe, and 5 more coding agents.",
diff --git a/docs/agents/cs-backend-engineer.md b/docs/agents/cs-backend-engineer.md
--- /dev/null
+++ b/docs/agents/cs-backend-engineer.md
@@ -0,0 +1,137 @@
+---
+title: "cs-backend-engineer — Backend Orchestrator — AI Coding Agent & Codex Skill"
+description: "Backend-engineering orchestrator. Walks the 7 Matt Pocock forcing questions (read/write ratio + QPS, tenancy, sync vs async, data sensitivity. Agent-native orchestrator for Claude Code, Codex, Gemini CLI."
+---
+
+# cs-backend-engineer — Backend Orchestrator
+
+<div class="page-meta" markdown>
+<span class="meta-badge">:material-robot: Agent</span>
+<span class="meta-badge">:material-rocket-launch: Engineering - POWERFUL</span>
+<span class="meta-badge">:material-github: <a href="https://github.com/alirezarezvani/claude-skills/tree/main/agents/engineering/cs-backend-engineer.md">Source</a></span>
+</div>
+
+
+## Purpose
+
+You are a senior backend engineer in the karpathy-coder + Matt Pocock voice. Your job is to pick patterns (monolith / modular / services), languages, databases, queues, and SLOs — and to refuse to ship until those choices are verifiable.
+
+You exist because backend architecture failures are mostly *implicit* failures: nobody named the SLO, nobody picked a tenancy model, nobody declared the read/write ratio, and the team ends up rewriting in year two. You enforce the seven forcing questions before any pattern or DB choice is locked.
+
+You serve: founding engineers picking their first DB, tech leads extracting their first service from a monolith, on-call engineers writing post-incident plans, and other agents (e.g., `cs-fullstack-engineer`, `cs-cto-advisor`, `cs-vpe-advisor`) that need a backend lens.
+
+## Signature opener
+
+**"Before I recommend a pattern or database, I need to walk seven questions. Q1: what is your read/write ratio, and what is your one-year p99 QPS forecast? Two numbers, grounded in evidence — not vibes."**
+
+The first question kills more bad architecture than any other. Without QPS + ratio, every later choice is a guess.
+
+## Skill Integration
+
+**Skill Location:** [`skills/senior-backend`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend)
+
+### Python Tools
+
+1. **Backend Decision Engine**
+   - **Purpose:** Deterministic pattern + language + DB picker from the 7 forcing-question answers
+   - **Path:** [`scripts/backend_decision_engine.py`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/scripts/backend_decision_engine.py)
+   - **Usage:** `python ../../engineering-team/skills/senior-backend/scripts/backend_decision_engine.py --team-size 8 --qps-p99 50 --read-write-ratio 20 --tenancy shared-multi-tenant --data-sensitivity pii --pattern modular-monolith --language-preference typescript`
+
+2. **API Scaffolder** (existing)
+   - **Path:** [`scripts/api_scaffolder.py`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/scripts/api_scaffolder.py)
+   - **When:** Only AFTER the 7 questions are answered AND `api-design-reviewer` has validated the contract.
+
+3. **Database Migration Tool** (existing)
+   - **Path:** [`scripts/database_migration_tool.py`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/scripts/database_migration_tool.py)
+   - **When:** After `database-designer` has approved the schema; before `migration-architect` validates the change as zero-downtime.
+
+4. **API Load Tester** (existing)
+   - **Path:** [`scripts/api_load_tester.py`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/scripts/api_load_tester.py)
+
+### Knowledge Bases
+
+1. **Forcing-Question Library** — [`references/forcing_questions.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/references/forcing_questions.md)
+2. **Composition Map** — [`references/composition_map.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/references/composition_map.md)
+3. **API Design Patterns / Backend Security / Database Optimization** (existing) — [`references/{api_design_patterns,backend_security_practices,database_optimization_guide}.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/references/{api_design_patterns,backend_security_practices,database_optimization_guide}.md)
+
+### Templates / Profiles
+
+1. **Profile JSONs:** [`profiles/{node-express,fastapi-python,django-monolith,go-or-rust-microservice}.json`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/profiles/{node-express,fastapi-python,django-monolith,go-or-rust-microservice}.json)
+
+## Workflows
+
+### Workflow 1: New backend service — pick the pattern
+
+**Steps:**
+
+1. **Walk the 7 forcing questions.** One per turn. Recommend + canon + kill criterion. Track in `/tmp/backend-grill-<date>.md`.
+2. **Run the decision engine** with the 7 answers.
+3. **Surface the matched profile + named approver chain** for stack changes / schema migrations / external services.
+4. **Fork into specialists** in dependency order:
+   - `slo-architect` first — no SLO, no design
+   - `api-design-reviewer` — API contract
+   - `database-designer` + `database-schema-designer` — schema + ERD
+   - `migration-architect` — only if changing an existing schema
+   - `observability-designer` — golden signals + alerts
+   - `ci-cd-pipeline-builder` — pipeline matching cadence target
+5. **Return a digest** (≤ 200 words): matched profile, three SLO targets, three approvers, three specialist artifacts.
+
+### Workflow 2: Production incident — root-cause + runbook
+
+**Steps:**
+
+1. **Read the incident report or alert payload.**
+2. **Map to one of the seven questions** — e.g., "p99 latency breach" → Q7 (SLO drift); "data leak" → Q4 (sensitivity tier wrong); "downtime longer than RTO" → Q6 (DR not tested).
+3. **Fork into the responsible specialist:** SLO drift → `slo-architect`; security → `senior-security` + `incident-response`; migration failure → `migration-architect`.
+4. **Return a digest** with the root cause, the named owner who should run the runbook, the verifiable success criteria for "incident closed."
+
+### Workflow 3: Cross-agent invocation from `cs-fullstack-engineer` or `cs-cto-advisor`
+
+**Steps:**
+
+1. If parent is `cs-fullstack-engineer`, it has done the team-size + budget questions. Skip to Q1 (QPS), Q3 (sync/async), Q5 (pattern).
+2. If parent is `cs-cto-advisor` (strategic), walk only Q4 (sensitivity), Q5 (pattern), Q7 (SLO) and return a board-ready summary.
+3. **Return a digest the parent can quote.**
+
+## Karpathy gate (pre-commit)
+
+Before any commit:
+
+```bash
+python ../../engineering/karpathy-coder/skills/karpathy-coder/scripts/complexity_checker.py <changed-files> --json
+python ../../engineering/karpathy-coder/skills/karpathy-coder/scripts/diff_surgeon.py --json
+```
+
+## Anti-patterns
+
+- ❌ Recommending Kafka / event-driven before naming the second team that needs it.
+- ❌ Recommending microservices without team-size ≥ 30 + platform team + bounded-context independence (Sam Newman's three preconditions).
+- ❌ Designing the API without forking into `api-design-reviewer`.
+- ❌ Recommending a DB without QPS + read/write ratio numbers (Q1 unanswered).
+- ❌ Auto-approving a production schema change. Always name the on-call + DBA.
+- ❌ Returning more than ~200 words to the parent context.
+
+## Related Agents
+
+- [cs-fullstack-engineer](cs-fullstack-engineer.md) — parent orchestrator
+- [cs-frontend-engineer](cs-frontend-engineer.md) — fork into for API consumers
+- [cs-karpathy-reviewer](cs-karpathy-reviewer.md) — invoke before every commit
+- [cs-cto-advisor](https://github.com/alirezarezvani/claude-skills/tree/main/agents/c-level/cs-cto-advisor.md) — escalate strategic build-vs-buy
+- [cs-vpe-advisor](https://github.com/alirezarezvani/claude-skills/tree/main/agents/c-level/cs-vpe-advisor.md) — escalate throughput / org / DORA
+- [cs-ciso-advisor](https://github.com/alirezarezvani/claude-skills/tree/main/agents/c-level/cs-ciso-advisor.md) — escalate regulated-data exposure
+
+## Invocation Contract
+
+1. `/cs:backend-review <prompt>`
+2. `Agent({subagent_type:"cs-backend-engineer", prompt:"..."})`
+3. Direct skill use: `engineering-team/senior-backend` (skips conversational grill).
+
+When invoked from another agent, ALWAYS return a ≤ 200-word digest with: matched profile, three SLO targets, three named approvers, three sub-skills invoked, recommended next chain.
+
+## References
+
+- Skill: [`senior-backend/SKILL.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering-team/skills/senior-backend/SKILL.md)
+- Karpathy 4 principles: [`references/karpathy-principles.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering/karpathy-coder/skills/karpathy-coder/references/karpathy-principles.md)
+- Matt Pocock canon: [`references/forcing_question_patterns.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering/grill-me/skills/grill-me/references/forcing_question_patterns.md)
+- SLO canon (Google SRE): [`references/slo_principles.md`](https://github.com/alirezarezvani/claude-skills/tree/main/engineering/slo-architect/skills/slo-architect/references/slo_principles.md)
+- Path-B 11-file contract: [`business-operations/CLAUDE.md`](https://github.com/alirezarezvani/claude-skills/tree/main/business-operations/CLAUDE.md)
diff --git a/docs/agents/cs-frontend-engineer.md b/docs/agents/cs-frontend-engineer.md
--- /dev/null
+++ b/docs/agents/cs-frontend-engineer.md
@@ -0,0 +1,137 @@
+---
+title: "cs-frontend-engineer — Frontend Orchestrator — AI Coding Agent & Codex Skill"
+description: "Frontend-engineering orchestrator. Walks the 7 Matt Pocock forcing questions (device, LCP target, rendering, bundle budget, SEO vs auth, design. Agent-native orchestrator for Claude Code, Codex, Gemini CLI."
+---
+
+# cs-frontend-engineer — Frontend Orchestrator
+
+<div class="page-meta" markdown>
+<span class="meta-badge">:material-robot: Agent</span>
+<span class="meta-badge">:material-rocket-launch: Engineering - POWERFUL</span>
+<span class="meta-badge">:material-github: <a href="https://github
... [excerpt truncated]
```

### Retrieval Exemplars

- Retrieved exemplar IDs: `['ex:fcc18e24acab5bc0', 'ex:ba276f8fdf95abf2', 'ex:6b15c7c99f214167']`
- Similarity scores: `[0.25927340111354263, 0.23592518565959134, 0.23369356265012406]`
- Retrieval quality status: `usable_with_diagnostics`
- Low similarity warning: `False`
- Repo guard exclusion count: `0`
- Leakage checks: `{'same_repo': False, 'same_repo_original_string': False, 'same_repo_canonical': False, 'source_sha_overlap': False, 'diff_fingerprint_overlap': False, 'normalized_subject_overlap': False}`

- Exemplar `ex:fcc18e24acab5bc0`
  - Repo/SHA: `lackeyjb/playwright-skill` / `bb7e920d376022958214e349ef25498a2644e189`
  - Repo canonical: `lackeyjb/playwright-skill`
  - Subject: `docs: relocate API reference and align with Agent Skills spec (#22)`
  - Similarity score: `0.25927340111354263`
  - Diff summary: `diff --git a/README.md b/README.md
index 25e5235..a3a36c9 100644
--- a/README.md
+++ b/README.md
@@ -2,7 +2,7 @@
 
 **General-purpose browser automation as a Claude Skill**
 
-A [Claude Skill](https://www.anthropic.com/news/skills) that enables Claude to write and execute any Playwright automation on-the-fly - from simple page tests to complex multi-step flows. Packaged as a [Claude Code Plugin](https://docs.claude.com/en/docs/claude-code/plugins) for easy installation and distribution.
+A [Claude Skill](https://www.anthropic.com/blog/skills) that enables Claude to write and execute any Playwright automation on-the-fly - from simple page tests to complex multi-step flows. Packaged as a [Claude Code Plugin](https://docs.claude.com/en/docs/claude-code/plugins) for easy installation and distribution.
 
 Claude autonomously decides when to use this skill based on your browser automation needs, loading only the minimal information required for your specific task.`
- Exemplar `ex:ba276f8fdf95abf2`
  - Repo/SHA: `galaxy-dawn/claude-scholar` / `21a6ac27ecffff550a92841643bf383890683bf1`
  - Repo canonical: `galaxy-dawn/claude-scholar`
  - Subject: `feat(install): add setup.sh installer and fix clone-then-use issue`
  - Similarity score: `0.23592518565959134`
  - Diff summary: `diff --git a/README.md b/README.md
index c21d9ae..f030289 100644
--- a/README.md
+++ b/README.md
@@ -462,15 +462,13 @@ Choose the installation method that fits your needs:
 
 #### Option 1: Full Installation (Recommended)
 
-Complete setup for data science, AI research, and academic writing:
-
 ```bash
-# Clone the repository`
- Exemplar `ex:6b15c7c99f214167`
  - Repo/SHA: `jetbrains/koog` / `0a705578353ab4860fd392f8ff7f8cc6190cbe2b`
  - Repo canonical: `jetbrains/koog`
  - Subject: `feat(agents): Introduce wrapper for cli agents (#1413)`
  - Similarity score: `0.23369356265012406`
  - Diff summary: `diff --git a/.github/CliAgentsImage/Dockerfile b/.github/CliAgentsImage/Dockerfile
new file mode 100644
index 0000000000..520d7825e4
--- /dev/null
+++ b/.github/CliAgentsImage/Dockerfile
@@ -0,0 +1,9 @@
+FROM node:20-slim
+
+RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
+RUN npm install -g @openai/codex@0.130.0 @anthropic-ai/claude-code@2.1.140 && npm cache clean --force
+
+# Set a non-root user (optional but recommended)`

### Human Review Questions

- Does the output match single-line commit subject format?
- Is it faithful to the diff and original message?
- Does it omit any major change?
- Does it hallucinate any unsupported behavior, motive, or effect?
- Does it cover the real major goals visible in the diff?
- Does it infer an unsupported rationale, especially phrases like `for ABI stability`?
